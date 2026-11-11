"""Application service orchestrating learning topics, sessions, attempts, and reviews."""

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Callable

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    AttemptDetailResponse,
    AttemptResultResponse,
    AttemptSummaryResponse,
    DashboardSummaryResponse,
    KnowledgeStateResponse,
    LearningHistoryEventResponse,
    LearningMaterialResponse,
    ReadingGroupEvaluation,
    ReviewItemResponse,
    SanitizedQuestionResponse,
    SessionDetailResponse,
    SessionSummaryResponse,
    TopicDetailResponse,
    TopicPrerequisiteSummary,
    TopicSummaryResponse,
    TransferCheckDispatchResponse,
    UnresolvedErrorReasonResponse,
)
from app.config import Settings
from app.decision.matching_headings import MatchingHeadingsRules, published_rules, supported_protocol
from app.application.exceptions import (
    ApplicationError,
    EntityNotFoundError,
    IdempotencyConflictError,
    InvalidSessionOperationError,
)
from app.domain.enums import (
    AttemptEvaluationStatus,
    DiagnosticCaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    KnowledgeMasteryStatus,
    QuestionRole,
    QuestionType,
    ReviewStatus,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.exceptions import (
    DomainRuleViolationError,
    InvalidStateTransitionError,
    UnverifiedMasteryError,
)
from app.domain.rules import validate_mastery_transition, validate_session_transition
from app.domain.reading_groups import HeadingAnswerKey, MatchingHeadingsGroup
from app.evaluation.ielts_reading_evaluator import IeltsReadingEvaluator
from app.evaluation.registry import evaluator_for_domain
from app.domain.exams import EXAM_CATALOG_VERSION, domain_for_variant
from app.persistence.models import ExamPreparationProfile, ReadingGroupVersion, ReadingRuleVersion
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    KnowledgeState,
    KnowledgeTopic,
    LearningMaterial,
    LearningSession,
    Hypothesis,
    Question,
    ReviewItem,
)
from app.persistence.repositories import LearningRepository
from app.persistence.models import utc_now


class LearningAppService:
    """Coordinates core learning use cases with explicit transaction boundaries."""

    def __init__(
        self,
        db_session: Session,
        *,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db_session
        self.repo = LearningRepository(db_session)
        self.review_intervals_days = (settings or Settings()).review_intervals_days
        if not self.review_intervals_days or any(day < 1 for day in self.review_intervals_days):
            raise ValueError("Review intervals must contain positive day counts.")
        self.clock = clock or utc_now

    def _now(self) -> datetime:
        value = self.clock()
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def _review_interval(self, stage: int) -> int:
        return self.review_intervals_days[min(max(stage, 0), len(self.review_intervals_days) - 1)]

    def _schedule_review(
        self, *, learner_id: str, topic_id: str, session_id: str,
        trigger_attempt_id: str, reason: str, stage: int = 0,
        retention_eligible: bool = True, hypothesis_id: str | None = None,
    ) -> ReviewItem:
        due_at = self._now() + timedelta(days=self._review_interval(stage))
        schedule_key = f"{'retention' if retention_eligible else 'remediation'}:{trigger_attempt_id}:stage:{stage}"
        if retention_eligible and stage == 0:
            superseded = self.repo.cancel_pending_review_items(
                learner_id=learner_id, topic_id=topic_id, except_schedule_key=schedule_key,
            )
            for prior in superseded:
                self.repo.append_decision_event(
                    session_id=session_id, event_type="review_plan_superseded",
                    to_state=ReviewStatus.CANCELLED.value, action="cancel_review_plan",
                    reason="A newer independent transfer result replaces the older pending review plan.",
                    payload_json={"review_item_id": prior.id, "replacement_trigger_attempt_id": trigger_attempt_id},
                    idempotency_key=f"review-cancel:{prior.id}:by:{trigger_attempt_id}",
                )
        item = self.repo.schedule_review_item(
            learner_id=learner_id, topic_id=topic_id, session_id=session_id,
            trigger_reason=reason, scheduled_for=due_at,
            schedule_key=schedule_key,
            review_stage=stage,
        )
        item.retention_eligible = retention_eligible
        if hypothesis_id is None:
            case = self.repo.latest_diagnostic_case(session_id)
            if case and self._is_tfng_session(case.session):
                supported = [h for h in case.hypotheses if h.status == HypothesisStatus.SUPPORTED.value]
                if len(supported) == 1:
                    hypothesis_id = supported[0].id
        if hypothesis_id is not None:
            item.hypothesis_id = hypothesis_id
        knowledge_state = self.repo.get_knowledge_state(learner_id, topic_id)
        if item.knowledge_state_id is None and knowledge_state is not None:
            item.knowledge_state_id = knowledge_state.id
        event = self.repo.append_decision_event(
            session_id=session_id, event_type="review_scheduled", to_state="pending",
            action="schedule_review", reason=reason,
            payload_json={"review_item_id": item.id, "scheduled_for": due_at.isoformat(),
                          "review_stage": stage, "interval_days": self._review_interval(stage),
                          "trigger_attempt_id": trigger_attempt_id,
                          "knowledge_state_id": item.knowledge_state_id,
                          "retention_eligible": retention_eligible},
            idempotency_key=f"review-schedule:{trigger_attempt_id}:stage:{stage}",
        )
        item.decision_event_id = event.id
        self.db.flush()
        return item

    # -----------------------------------------------------------------------
    # Helper: Sanitization
    # -----------------------------------------------------------------------

    @staticmethod
    def sanitize_question(q: Question) -> SanitizedQuestionResponse:
        """Convert a Question entity into a sanitized payload without answer leaks."""
        return SanitizedQuestionResponse(
            id=q.id,
            topic_id=q.topic_id,
            material_id=q.material_id,
            parent_question_id=q.parent_question_id,
            question_role=QuestionRole(q.question_role),
            question_type=QuestionType(q.question_type),
            prompt_text=q.prompt_text,
            context_snippet=q.context_snippet,
            difficulty=q.difficulty,
            version=q.version,
        )

    # -----------------------------------------------------------------------
    # 1. Topics & Materials & Questions
    # -----------------------------------------------------------------------

    def list_topics(self, domain_code: str | None = None) -> list[TopicSummaryResponse]:
        """List all available knowledge topics, optionally filtered by domain."""
        topics = self.repo.list_topics(domain_code=domain_code)
        return [
            TopicSummaryResponse(
                id=t.id,
                slug=t.slug,
                domain_code=t.domain_code,
                title=t.title,
                summary=t.summary,
                difficulty_level=t.difficulty_level,
                prerequisite_ids=[p.id for p in t.prerequisites],
            )
            for t in topics
        ]

    def get_topic_detail(self, topic_id_or_slug: str) -> TopicDetailResponse:
        """Get complete topic details with prerequisites and materials."""
        topic = self.repo.get_topic_by_id(topic_id_or_slug)
        if topic is None:
            topic = self.repo.get_topic_by_slug(topic_id_or_slug)
        if topic is None:
            raise EntityNotFoundError("KnowledgeTopic", topic_id_or_slug)

        prereqs = [
            TopicPrerequisiteSummary(id=p.id, slug=p.slug, title=p.title)
            for p in topic.prerequisites
        ]
        # Reading passages are released with the currently assigned question.
        # Returning every passage here would expose future transfer/review contexts.
        visible_materials = [] if topic.domain_code in {"ielts_academic", "ielts_general_training"} else topic.materials
        materials = [
            LearningMaterialResponse(
                id=m.id,
                topic_id=m.topic_id,
                title=m.title,
                summary=m.summary,
                content_body=m.content_body,
                content_format=m.content_format,
                version=m.version,
            )
            for m in visible_materials
        ]
        questions = self.repo.list_questions_for_topic(topic.id)

        return TopicDetailResponse(
            id=topic.id,
            slug=topic.slug,
            domain_code=topic.domain_code,
            title=topic.title,
            summary=topic.summary,
            difficulty_level=topic.difficulty_level,
            prerequisites=prereqs,
            materials=materials,
            questions_count=len(questions),
        )

    def get_topic_materials(self, topic_id_or_slug: str) -> list[LearningMaterialResponse]:
        """List all learning materials attached to a topic."""
        detail = self.get_topic_detail(topic_id_or_slug)
        return detail.materials

    def get_current_session_material(self, session_id: str) -> LearningMaterialResponse | None:
        session = self.repo.get_session(session_id)
        if session is None:
            raise EntityNotFoundError("LearningSession", session_id)
        question = self.repo.get_question_by_id(session.current_question_id) if session.current_question_id else None
        material = question.material if question else None
        if material is None:
            return None
        return LearningMaterialResponse(id=material.id, topic_id=material.topic_id, title=material.title,
                                        summary=material.summary, content_body=material.content_body,
                                        content_format=material.content_format, version=material.version)

    def get_sanitized_question(self, question_id: str) -> SanitizedQuestionResponse:
        """Get a single question by ID, strictly sanitized to protect rubrics/answers."""
        q = self.repo.get_question_by_id(question_id)
        if q is None:
            raise EntityNotFoundError("Question", question_id)
        return self.sanitize_question(q)

    # -----------------------------------------------------------------------
    # 2. Learning Sessions
    # -----------------------------------------------------------------------

    def create_session(
        self,
        topic_id: str,
        learner_id: str = "default_learner",
        initial_question_id: str | None = None,
        exam_variant: str | None = None,
        question_type: QuestionType | None = None,
    ) -> SessionDetailResponse:
        """Create and initialize a new learning session."""
        topic = self.repo.get_topic_by_id(topic_id)
        if topic is None:
            topic = self.repo.get_topic_by_slug(topic_id)
        if topic is None:
            raise EntityNotFoundError("KnowledgeTopic", topic_id)

        # Resolve initial question (must belong to topic AND have role == 'initial')
        if initial_question_id:
            init_q = self.repo.get_question_by_id(initial_question_id)
            if init_q is None or init_q.topic_id != topic.id:
                raise EntityNotFoundError("Question", initial_question_id)
            if init_q.question_role != QuestionRole.INITIAL.value:
                raise DomainRuleViolationError(
                    f"Question '{init_q.id}' has role '{init_q.question_role}'; "
                    "session initial_question_id must have question_role='initial'."
                )
            if question_type is not None and init_q.question_type != question_type.value:
                raise DomainRuleViolationError("The requested initial question does not match question_type.")
            selected_q_id = init_q.id
        else:
            initial_qs = self.repo.list_questions_for_topic(
                topic.id, role=QuestionRole.INITIAL
            )
            if question_type is not None:
                initial_qs = [q for q in initial_qs if q.question_type == question_type.value]
            if not initial_qs:
                raise DomainRuleViolationError(
                    f"Topic '{topic.slug}' has no initial questions configured."
                )
            selected_q_id = initial_qs[0].id
        selected_question = self.repo.get_question_by_id(selected_q_id)
        if selected_question.question_type == QuestionType.MATCHING_HEADINGS.value and not selected_question.reading_group_version_id:
            raise DomainRuleViolationError("Matching Headings requires a published reading group.")

        if topic.domain_code.startswith("ielts_"):
            profile = self.db.get(ExamPreparationProfile, learner_id)
            selected_variant = exam_variant or (profile.exam_variant if profile else None)
            if selected_variant is None or domain_for_variant(selected_variant) != topic.domain_code:
                raise DomainRuleViolationError("选择的考试模式与阅读材料不匹配，请先保存 Academic 或 General Training 目标。")
            if profile is None or profile.exam_variant != selected_variant:
                raise DomainRuleViolationError("请先将所选 IELTS 考试模式保存到学习档案。")
            session_exam_variant = selected_variant
            session_spec_version = EXAM_CATALOG_VERSION
        else:
            if exam_variant is not None:
                raise DomainRuleViolationError("非 IELTS 学习会话不能携带 IELTS 考试模式。")
            session_exam_variant = None
            session_spec_version = None

        learning_session = self.repo.create_session(
            topic_id=topic.id,
            learner_id=learner_id,
            current_question_id=selected_q_id,
            exam_variant=session_exam_variant,
            exam_spec_version=session_spec_version,
        )
        self.db.commit()

        return self.get_session_detail(learning_session.id)

    def _resolve_knowledge_state_fields(
        self, learner_id: str, topic_id: str
    ) -> tuple[KnowledgeMasteryStatus | None, bool]:
        """Return (knowledge_state_status, topic_mastered) for a learner and topic."""
        ks = self.repo.get_knowledge_state(learner_id, topic_id)
        if ks is None:
            return None, False
        ks_enum = KnowledgeMasteryStatus(ks.status)
        return ks_enum, (ks_enum == KnowledgeMasteryStatus.STABLE)

    def _is_tfng_session(self, sess: LearningSession) -> bool:
        initial = next((a for a in self.repo.list_attempts_for_session(sess.id)
                        if a.attempt_role == QuestionRole.INITIAL.value), None)
        if initial is not None:
            return initial.question_snapshot_json.get('diagnostic_protocol') == 'tfng-v1'
        return any(q.question_role == QuestionRole.INITIAL.value and
                   (q.evaluation_rubric or {}).get('diagnostic_protocol') == 'tfng-v1'
                   for q in self.repo.list_questions_for_topic(sess.topic_id))

    def _select_fresh_transfer_question(self, sess: LearningSession) -> Question | None:
        candidates = self.repo.fresh_transfer_questions(sess)
        if self._is_tfng_session(sess):
            case = self.repo.latest_diagnostic_case(sess.id)
            states = {h.error_code: h.status for h in case.hypotheses} if case else {}
            targets = [code for code, other in (('true_false_not_given', 'passage_location'),
                                                ('passage_location', 'true_false_not_given'))
                       if states.get(code) == 'supported' and states.get(other) == 'lowered']
            if len(targets) != 1:
                return None
            initial = next((a for a in self.repo.list_attempts_for_session(sess.id)
                            if a.attempt_role == QuestionRole.INITIAL.value), None)
            version = initial.question_snapshot_json.get('diagnostic_version') if initial else None
            candidates = [q for q in candidates if version and
                          (q.evaluation_rubric or {}).get('diagnostic_protocol') == 'tfng-v1' and
                          (q.evaluation_rubric or {}).get('diagnostic_version') == version and
                          (q.evaluation_rubric or {}).get('target_error_codes') == targets]
        return candidates[0] if candidates else None

    def _enter_transfer(self, sess: LearningSession, reason: str) -> Question | None:
        """Synchronize the existing session and diagnostic state machines."""
        if sess.status != SessionStatus.TRANSFER_CHECKING.value:
            self.repo.transition_session_status(sess, SessionStatus.TRANSFER_CHECKING)
        case = self.repo.latest_diagnostic_case(sess.id)
        question = self._select_fresh_transfer_question(sess)
        sess.current_question_id = question.id if question else None
        if case and case.status != DiagnosticCaseStatus.RESOLVED.value and question is not None:
            if case.status not in (DiagnosticCaseStatus.INTERVENTION_SELECTED.value, DiagnosticCaseStatus.TRANSFER_CHECKING.value):
                self.repo.transition_diagnostic_case(
                    case, DiagnosticCaseStatus.INTERVENTION_SELECTED,
                    action="prepare_transfer_verification", reason=reason,
                    selected_intervention="transfer_check",
                )
            if case.status != DiagnosticCaseStatus.TRANSFER_CHECKING.value:
                self.repo.transition_diagnostic_case(
                    case, DiagnosticCaseStatus.TRANSFER_CHECKING,
                    action="assign_transfer_verification", reason=reason,
                    selected_intervention="transfer_check",
                    uncertainty_note="需要独立新情境作答；练习正确尚不能证明迁移或长期保持。",
                    payload_json={"selected_question_id": question.id if question else None},
                )
        elif case and question is None and case.status in (
            DiagnosticCaseStatus.INTERVENTION_SELECTED.value, DiagnosticCaseStatus.TRANSFER_CHECKING.value,
        ):
            self.repo.transition_diagnostic_case(
                case, DiagnosticCaseStatus.NEEDS_EVIDENCE,
                action="transfer_evidence_unavailable", reason="No independent transfer question is available.",
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note="缺少未见过的独立迁移题；保留不确定性，可继续针对性干预。",
            )
        if question is None and self.db.scalar(select(DecisionEvent.id).where(
            DecisionEvent.session_id == sess.id, DecisionEvent.action == "transfer_questions_exhausted",
        )) is None:
            self.repo.append_decision_event(
                session_id=sess.id, diagnostic_case_id=case.id if case else None,
                event_type="transfer_questions_exhausted", action="transfer_questions_exhausted",
                to_state=sess.status, reason="暂无未见过的独立迁移题；保留证据不足，不重复使用旧题。",
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            )
        return question

    def get_session_detail(self, session_id: str) -> SessionDetailResponse:
        """Fetch session detail including current sanitized question, diagnostic case pointer, and mastery status."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        current_q_dto = None
        current_question = self.repo.get_question_by_id(sess.current_question_id) if sess.current_question_id else None
        if current_question:
            current_q_dto = self.sanitize_question(current_question)
            if sess.current_group_version_id:
                group = self._assigned_reading_group(sess, current_question)
                current_q_dto.group_version_id = group.id
                current_q_dto.group_display = group.display_json
            elif current_question.reading_group_version_id:
                raise DomainRuleViolationError("The assigned reading group version was not pinned for this session.")

        # Find latest active or incomplete diagnostic case
        active_diag = (
            self.db.scalars(
                select(DiagnosticCase)
                .where(DiagnosticCase.session_id == sess.id)
                .order_by(DiagnosticCase.created_at.desc())
            ).first()
        )
        ks_status, topic_mastered = self._resolve_knowledge_state_fields(
            sess.learner_id, sess.topic_id
        )
        history = self.repo.list_attempts_for_session(sess.id)
        latest_result = self._stored_attempt_result(sess.id, history[-1].id) if history else None
        try:
            self.repo.validate_transfer_readiness(sess)
            can_dispatch_transfer = True
        except DomainRuleViolationError:
            can_dispatch_transfer = False

        return SessionDetailResponse(
            id=sess.id,
            topic_id=sess.topic_id,
            topic_title=sess.topic.title,
            learner_id=sess.learner_id,
            exam_variant=sess.exam_variant,
            exam_spec_version=sess.exam_spec_version,
            status=SessionStatus(sess.status),
            knowledge_state_status=ks_status,
            topic_mastered=topic_mastered,
            current_question_id=sess.current_question_id,
            current_question=current_q_dto,
            active_diagnostic_case_id=active_diag.id if active_diag else None,
            latest_attempt_result=latest_result,
            can_dispatch_transfer=can_dispatch_transfer,
            attempts_count=len(sess.attempts),
            started_at=sess.started_at,
            updated_at=sess.updated_at,
            completed_at=sess.completed_at,
        )

    def list_sessions(
        self,
        learner_id: str = "default_learner",
        status: str | None = None,
    ) -> list[SessionSummaryResponse]:
        """List historical learning sessions for a learner."""
        sessions = self.repo.list_sessions_for_learner(learner_id=learner_id)
        if status:
            sessions = [s for s in sessions if s.status == status]

        results: list[SessionSummaryResponse] = []
        for s in sessions:
            ks_status, topic_mastered = self._resolve_knowledge_state_fields(
                s.learner_id, s.topic_id
            )
            results.append(
                SessionSummaryResponse(
                    id=s.id,
                    topic_id=s.topic_id,
                    topic_title=s.topic.title,
                    learner_id=s.learner_id,
                    exam_variant=s.exam_variant,
                    exam_spec_version=s.exam_spec_version,
                    status=SessionStatus(s.status),
                    knowledge_state_status=ks_status,
                    topic_mastered=topic_mastered,
                    current_question_id=s.current_question_id,
                    attempts_count=len(s.attempts),
                    started_at=s.started_at,
                    updated_at=s.updated_at,
                    completed_at=s.completed_at,
                )
            )
        return results

    def pause_session(
        self,
        session_id: str,
        reason: str | None = None,
    ) -> SessionDetailResponse:
        """Pause an active or diagnosing session per domain state machine rules."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        if sess.status == SessionStatus.PAUSED.value:
            return self.get_session_detail(sess.id)

        old_status = sess.status
        self.repo.transition_session_status(sess, SessionStatus.PAUSED)
        self.repo.append_decision_event(
            session_id=sess.id,
            event_type="session_paused",
            from_state=old_status,
            to_state=SessionStatus.PAUSED.value,
            action="pause_session",
            reason=reason or "User or tutor requested session pause.",
        )
        self.db.commit()
        return self.get_session_detail(sess.id)

    def resume_session(
        self,
        session_id: str,
        reason: str | None = None,
    ) -> SessionDetailResponse:
        """Resume a paused session back to its active/diagnosing state."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        if sess.status != SessionStatus.PAUSED.value:
            raise InvalidSessionOperationError(
                f"Cannot resume session '{sess.id}' because current status is '{sess.status}', not 'paused'."
            )

        # Restore the prior session state from the latest pause DecisionEvent if available
        pause_evt = (
            self.db.scalars(
                select(DecisionEvent)
                .where(
                    DecisionEvent.session_id == sess.id,
                    DecisionEvent.event_type == "session_paused",
                )
                .order_by(DecisionEvent.created_at.desc())
            ).first()
        )
        if pause_evt and pause_evt.from_state in (
            SessionStatus.ACTIVE.value,
            SessionStatus.DIAGNOSING.value,
            SessionStatus.INTERVENING.value,
            SessionStatus.TRANSFER_CHECKING.value,
            SessionStatus.REVIEWING.value,
        ):
            target_status = SessionStatus(pause_evt.from_state)
        else:
            active_diag = (
                self.db.scalars(
                    select(DiagnosticCase).where(
                        DiagnosticCase.session_id == sess.id,
                        DiagnosticCase.status != DiagnosticCaseStatus.RESOLVED.value,
                    )
                ).first()
            )
            target_status = (
                SessionStatus.DIAGNOSING if active_diag else SessionStatus.ACTIVE
            )

        self.repo.transition_session_status(sess, target_status)
        self.repo.append_decision_event(
            session_id=sess.id,
            event_type="session_resumed",
            from_state=SessionStatus.PAUSED.value,
            to_state=target_status.value,
            action="resume_session",
            reason=reason or "User resumed paused learning session.",
        )
        self.db.commit()
        return self.get_session_detail(sess.id)

    def complete_session(
        self,
        session_id: str,
        reason: str | None = None,
    ) -> SessionDetailResponse:
        """Complete a learning session in TRANSFER_CHECKING state.

        Strictly distinguishes:
        - Session ended (`session.status == 'completed'`)
        - Topic mastered (`KnowledgeState.status == 'stable'`)
        - Transfer failed / needs practice (`KnowledgeState.status == 'needs_practice'`)

        Completing a session NEVER fabricates or promotes KnowledgeState to `stable`.
        Requires at least one transfer_check attempt in the session (or documented transfer question exhaustion).
        """
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        # Domain invariant: validate transition from TRANSFER_CHECKING to COMPLETED
        validate_session_transition(sess.status, SessionStatus.COMPLETED)

        has_transfer_attempt = any(
            att.attempt_role == QuestionRole.TRANSFER_CHECK.value
            for att in sess.attempts
        )
        has_exhausted_degrade = (
            self.db.scalars(
                select(DecisionEvent).where(
                    DecisionEvent.session_id == sess.id,
                    DecisionEvent.action.in_(
                        (
                            "exhausted_transfer_questions_degrade",
                            "transfer_questions_exhausted",
                        )
                    ),
                )
            ).first()
            is not None
        )
        if not has_transfer_attempt and not has_exhausted_degrade:
            raise InvalidSessionOperationError(
                "Cannot complete session in 'transfer_checking' before submitting a transfer verification attempt.",
                current_state=sess.status,
            )

        ks = self.repo.get_knowledge_state(sess.learner_id, sess.topic_id)
        if ks is not None and ks.status == KnowledgeMasteryStatus.TRANSFER_VERIFIED.value:
            event_type = "session_completed_without_mastery"
            default_reason = "Independent transfer passed; delayed retention remains unverified."
        elif ks is None or ks.status != KnowledgeMasteryStatus.STABLE.value:
            # Ensure ending a session without passing transfer check leaves KnowledgeState in needs_practice (never stable)
            if ks is None:
                ks = self.repo.update_knowledge_state(
                    session_id=sess.id,
                    topic_id=sess.topic_id,
                    target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
                    reason="Session ended in transfer_checking without passing independent transfer verification.",
                    learner_id=sess.learner_id,
                )
            event_type = "session_completed_without_mastery"
            default_reason = (
                "Completed learning session; topic remains in 'needs_practice' (not mastered)."
            )
        else:
            event_type = "session_completed"
            default_reason = (
                "Completed learning session following verified transfer mastery ('stable')."
            )

        old_status = sess.status
        self.repo.transition_session_status(sess, SessionStatus.COMPLETED)
        self.repo.append_decision_event(
            session_id=sess.id,
            event_type=event_type,
            from_state=old_status,
            to_state=SessionStatus.COMPLETED.value,
            action="complete_session",
            reason=reason or default_reason,
            payload_json={
                "knowledge_state_status": ks.status,
                "topic_mastered": ks.status == KnowledgeMasteryStatus.STABLE.value,
            },
        )
        self.db.commit()
        return self.get_session_detail(sess.id)

    # -----------------------------------------------------------------------
    # 3. User Attempts & Answer Submissions
    # -----------------------------------------------------------------------

    def submit_attempt(
        self,
        session_id: str,
        question_id: str,
        submitted_answer: str | None = None,
        idempotency_key: str | None = None,
        group_version_id: str | None = None,
        structured_answer: dict[str, str] | None = None,
    ) -> AttemptResultResponse:
        """Record and evaluate a user attempt, updating diagnostic and mastery states."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        if (submitted_answer is None) == (structured_answer is None):
            raise DomainRuleViolationError("Provide exactly one of submitted_answer and structured_answer.")
        if structured_answer is not None:
            return self._submit_reading_group(sess, question_id, group_version_id, structured_answer, idempotency_key or None)
        if sess.current_group_version_id or group_version_id:
            if group_version_id != sess.current_group_version_id:
                raise DomainRuleViolationError("The submitted reading group version does not match the assigned version.")
            raise DomainRuleViolationError("Matching Headings requires structured_answer.")

        question = self.repo.get_question_by_id(question_id)
        if question is None:
            raise EntityNotFoundError("Question", question_id)

        if question.question_type == QuestionType.MATCHING_HEADINGS.value or question.reading_group_version_id:
            raise DomainRuleViolationError("The assigned reading group version was not pinned for this session.")

        if question.topic_id != sess.topic_id:
            raise DomainRuleViolationError(
                f"Question '{question.id}' belongs to topic '{question.topic_id}', "
                f"which does not match session topic '{sess.topic_id}'."
            )

        # 1. Idempotency check FIRST:
        #    - If same idempotency_key + same (question_id, submitted_answer), replay result even if session advanced.
        #    - If same idempotency_key + different (question_id, submitted_answer), raise 409 IdempotencyConflictError.
        if idempotency_key:
            existing_attempt = (
                self.db.scalars(
                    select(Attempt).where(
                        Attempt.idempotency_key == idempotency_key,
                    )
                ).first()
            )
            if existing_attempt is not None:
                if (
                    existing_attempt.session_id != sess.id
                    or existing_attempt.question_id != question.id
                    or existing_attempt.submitted_answer != submitted_answer
                    or existing_attempt.group_version_id is not None
                ):
                    raise IdempotencyConflictError(
                        idempotency_key,
                        "Idempotency key was already used with a different question_id or submitted_answer.",
                    )
                stored = self._stored_attempt_result(sess.id, existing_attempt.id)
                if stored is not None:
                    return stored
                return self._build_attempt_result(sess, existing_attempt, question)

        # 2. Session active status check
        if sess.status in (SessionStatus.PAUSED.value, SessionStatus.COMPLETED.value):
            raise InvalidSessionOperationError(
                f"Cannot submit answers while session is in '{sess.status}' status.",
                current_state=sess.status,
            )

        # 3. Assigned question authorization check:
        #    Only the question currently assigned to `sess.current_question_id` may be answered.
        if sess.current_question_id != question.id:
            raise InvalidSessionOperationError(
                f"Question '{question.id}' (role='{question.question_role}') is not the currently assigned "
                f"question ('{sess.current_question_id}') for session '{sess.id}'.",
                current_state=sess.status,
            )

        # 4. Question role vs session workflow stage consistency check:
        role = QuestionRole(question.question_role)
        allowed_statuses_by_role: dict[QuestionRole, set[str]] = {
            QuestionRole.INITIAL: {SessionStatus.ACTIVE.value},
            QuestionRole.DIAGNOSTIC_FOLLOWUP: {SessionStatus.DIAGNOSING.value},
            QuestionRole.TARGETED_PRACTICE: {
                SessionStatus.INTERVENING.value,
                SessionStatus.DIAGNOSING.value,
            },
            QuestionRole.TRANSFER_CHECK: {SessionStatus.TRANSFER_CHECKING.value},
            QuestionRole.REVIEW: {SessionStatus.REVIEWING.value},
        }
        if sess.status not in allowed_statuses_by_role.get(role, set()):
            raise InvalidSessionOperationError(
                f"Cannot submit question '{question.id}' with role '{role.value}' "
                f"while session is in '{sess.status}' stage.",
                current_state=sess.status,
            )

        review_item = None
        if role == QuestionRole.REVIEW:
            review_item = self.repo.get_review_item_for_session(sess.id)
            if (
                review_item is None
                or review_item.learner_id != sess.learner_id
                or review_item.status != ReviewStatus.PENDING.value
                or review_item.question_id != question.id
            ):
                raise InvalidSessionOperationError(
                    "This review question is not assigned to an active review item.",
                    current_state=sess.status,
                )
            if self._now() < self._as_utc(review_item.scheduled_for):
                raise InvalidSessionOperationError("This review is not due yet.", current_state=review_item.status)

        # 5. Same-question retry guardrails:
        #    - For diagnostic_followup: once answered in the current diagnostic turn, require an Agent step before another attempt.
        #    - For transfer_check: if already answered correctly in this session, forbid redundant re-submissions.
        if role == QuestionRole.TARGETED_PRACTICE and any(
            prior.question_id == question.id for prior in sess.attempts
        ):
            raise InvalidSessionOperationError(
                "This targeted practice has already been evaluated; request a new server intervention.",
                current_state=sess.status,
            )
        if role == QuestionRole.DIAGNOSTIC_FOLLOWUP:
            latest_followup_dispatch = (
                self.db.scalars(
                    select(DecisionEvent)
                    .where(
                        DecisionEvent.session_id == sess.id,
                        DecisionEvent.action == "select_diagnostic_followup",
                    )
                    .order_by(DecisionEvent.created_at.desc())
                ).first()
            )
            prior_followup_attempts = [
                att
                for att in sess.attempts
                if att.question_id == question.id
                and (
                    latest_followup_dispatch is None
                    or att.submitted_at >= latest_followup_dispatch.created_at
                )
            ]
            if prior_followup_attempts:
                raise InvalidSessionOperationError(
                    f"Diagnostic follow-up question '{question.id}' has already been answered in the current turn; "
                    "execute the next diagnostic step before submitting another attempt.",
                    current_state=sess.status,
                )
        elif role == QuestionRole.TRANSFER_CHECK:
            already_passed_in_session = any(
                att.question_id == question.id and att.is_correct is True
                for att in sess.attempts
            )
            if already_passed_in_session:
                raise InvalidSessionOperationError(
                    f"Transfer verification question '{question.id}' has already been answered correctly in this session; "
                    "dispatch a fresh transfer question or complete the session.",
                    current_state=sess.status,
                )

        # Record initial pending Attempt
        try:
            attempt = self.repo.record_attempt(
                session_id=sess.id, question_id=question.id, submitted_answer=submitted_answer,
                evaluation_status=AttemptEvaluationStatus.PENDING, idempotency_key=idempotency_key,
                submitted_at=self._now(),
            )
        except IntegrityError:
            # A second client may race the same intent past the initial read.
            self.db.rollback()
            existing = self.db.scalar(select(Attempt).where(Attempt.idempotency_key == idempotency_key)) if idempotency_key else None
            if existing is None and role == QuestionRole.REVIEW:
                # Review questions admit only one evaluated attempt per session, even
                # when clients omit an idempotency key or race with different keys.
                existing = self.db.scalar(select(Attempt).where(
                    Attempt.session_id == session_id,
                    Attempt.question_id == question_id,
                    Attempt.attempt_role == QuestionRole.REVIEW.value,
                ))
            if existing is None:
                raise
            if existing.group_version_id is not None or (existing.session_id, existing.question_id, existing.submitted_answer) != (session_id, question_id, submitted_answer):
                raise IdempotencyConflictError(idempotency_key or "review-attempt", "This review question already has a different submitted answer.")
            stored_result = self._stored_attempt_result(session_id, existing.id)
            if stored_result is not None:
                return stored_result
            if role == QuestionRole.REVIEW:
                raise InvalidSessionOperationError(
                    "A concurrent review submission is being finalized; reload the review status before retrying.",
                    current_state="review_submission_in_progress",
                )
            return self._build_attempt_result(self.repo.get_session(session_id), existing, question)
        if attempt.group_version_id is not None or (attempt.session_id, attempt.question_id, attempt.submitted_answer) != (session_id, question_id, submitted_answer):
            raise IdempotencyConflictError(idempotency_key or "", "Idempotency key belongs to a different answer intent.")
        stored = self._stored_attempt_result(sess.id, attempt.id)
        if stored:
            return stored

        # Run local rule pre-evaluator
        rule_res = evaluator_for_domain(sess.topic.domain_code).evaluate_attempt(
            attempt=attempt,
            question=question,
            topic=sess.topic,
        )

        # Finalize evaluated status and immutable summary
        attempt.is_correct = rule_res.answer_matches_standard
        attempt.evaluation_status = AttemptEvaluationStatus.EVALUATED.value
        attempt.evaluation_summary = rule_res.summary
        self.db.flush()

        next_action = "continue"
        diag_case_id: str | None = None
        ks_status: str | None = None

        if role == QuestionRole.INITIAL:
            if not rule_res.answer_matches_standard:
                # Wrong answer: must transition to DIAGNOSING and create DiagnosticCase
                if sess.status != SessionStatus.DIAGNOSING.value:
                    self.repo.transition_session_status(sess, SessionStatus.DIAGNOSING)
                diag_case = self.repo.create_diagnostic_case(
                    session_id=sess.id,
                    trigger_attempt_id=attempt.id,
                    uncertainty_note=rule_res.summary,
                )
                diag_case_id = diag_case.id
                next_action = "diagnose"
            else:
                # Initial answer matches standard answer
                if not rule_res.has_reasoning_or_trace and question.question_type == QuestionType.CODE_TRACE.value:
                    # Output matches but no trace: enter diagnosis to probe understanding
                    if sess.status != SessionStatus.DIAGNOSING.value:
                        self.repo.transition_session_status(sess, SessionStatus.DIAGNOSING)
                    diag_case = self.repo.create_diagnostic_case(
                        session_id=sess.id,
                        trigger_attempt_id=attempt.id,
                        uncertainty_note="Initial output correct but trace not provided; checking mental model.",
                    )
                    diag_case_id = diag_case.id
                    next_action = "diagnose"
                else:
                    # Fully verified correct initial answer: proceed to transfer check
                    fresh_transfer = self._enter_transfer(sess, "Initial answer includes reasoning; verify in a new situation.")
                    next_action = "transfer_check" if fresh_transfer else "transfer_unavailable"

        elif role == QuestionRole.DIAGNOSTIC_FOLLOWUP:
            # Attach follow-up evidence to active diagnostic case
            active_diag = (
                self.db.scalars(
                    select(DiagnosticCase)
                    .where(
                        DiagnosticCase.session_id == sess.id,
                        DiagnosticCase.status != DiagnosticCaseStatus.RESOLVED.value,
                    )
                    .order_by(DiagnosticCase.created_at.desc())
                ).first()
            )
            if active_diag:
                diag_case_id = active_diag.id
                next_action = "diagnose_step"

        elif role == QuestionRole.TARGETED_PRACTICE:
            active_diag = self.repo.latest_diagnostic_case(sess.id)
            diag_case_id = active_diag.id if active_diag else None
            if attempt.is_correct:
                fresh_transfer = self._enter_transfer(sess, "Targeted practice passed; independent transfer is still required.")
                next_action = "transfer_check" if fresh_transfer else "transfer_unavailable"
                ks = self.repo.update_knowledge_state(
                    session_id=sess.id, topic_id=sess.topic_id, learner_id=sess.learner_id,
                    target_status=KnowledgeMasteryStatus.INSUFFICIENT_EVIDENCE,
                    reason="Targeted practice passed, but independent transfer and long-term retention remain unverified.",
                )
                ks_status = ks.status
            else:
                next_action = "diagnose_step"
                self.repo.transition_session_status(sess, SessionStatus.DIAGNOSING)
                if active_diag and active_diag.status == DiagnosticCaseStatus.INTERVENTION_SELECTED.value:
                    self.repo.transition_diagnostic_case(
                        active_diag, DiagnosticCaseStatus.NEEDS_EVIDENCE,
                        action="practice_failed", reason="Practice result requires further diagnosis or intervention.",
                        uncertainty_note="针对性练习未通过；尚不能确定错误原因或进入迁移验证。",
                    )
                ks = self.repo.update_knowledge_state(
                    session_id=sess.id, topic_id=sess.topic_id, learner_id=sess.learner_id,
                    target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
                    reason="Targeted practice failed; collect more evidence before transfer.",
                )
                ks_status = ks.status

        elif role == QuestionRole.TRANSFER_CHECK:
            active_diag = self.repo.latest_diagnostic_case(sess.id)
            diag_case_id = active_diag.id if active_diag else None
            if not attempt.is_correct:
                # Transfer check failed: schedule review and retain needs_practice
                self._schedule_review(
                    topic_id=sess.topic_id,
                    session_id=sess.id,
                    learner_id=sess.learner_id,
                    trigger_attempt_id=attempt.id,
                    reason=f"Transfer verification question '{question.id}' failed; preserve a short-interval follow-up.",
                    retention_eligible=False,
                )
                ks = self.repo.update_knowledge_state(
                    session_id=sess.id,
                    topic_id=sess.topic_id,
                    target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
                    reason=f"Failed transfer check '{question.id}'.",
                    learner_id=sess.learner_id,
                )
                ks_status = ks.status
                next_action = "transfer_failed_needs_practice"
                if active_diag and active_diag.status == DiagnosticCaseStatus.TRANSFER_CHECKING.value:
                    self.repo.transition_diagnostic_case(
                        active_diag, DiagnosticCaseStatus.NEEDS_EVIDENCE,
                        action="transfer_failed", reason="Transfer failed; retain competing explanations and allow further intervention.",
                        uncertainty_note="独立迁移未通过，仍需针对性干预或新的区分性证据。",
                    )
            else:
                # Transfer check passed: verify it is NOT a retried question
                # Query prior attempts for this learner on this exact question_id
                prior_fails = (
                    self.db.scalars(
                        select(Attempt)
                        .join(LearningSession, Attempt.session_id == LearningSession.id)
                        .where(
                            LearningSession.learner_id == sess.learner_id,
                            Attempt.question_id == question.id,
                            Attempt.id != attempt.id,
                            Attempt.is_correct.is_(False),
                        )
                    ).all()
                )
                if prior_fails:
                    # Enforce Stage 3 principle: Retrying same question CANNOT grant stable
                    ks = self.repo.update_knowledge_state(
                        session_id=sess.id,
                        topic_id=sess.topic_id,
                        target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
                        reason=f"Retried transfer question '{question.id}' answered correctly, but requires fresh unattempted question for stable.",
                        learner_id=sess.learner_id,
                    )
                    ks_status = ks.status
                    next_action = "transfer_retry_blocked"
                else:
                    # Clean independent transfer verification: promote to STABLE
                    tfng = self._is_tfng_session(sess)
                    ks = self.repo.update_knowledge_state(
                        session_id=sess.id,
                        topic_id=sess.topic_id,
                        target_status=(KnowledgeMasteryStatus.TRANSFER_VERIFIED if tfng else KnowledgeMasteryStatus.STABLE),
                        reason=f"Passed independent fresh transfer verification '{question.id}'.",
                        transfer_attempt_id=attempt.id,
                        learner_id=sess.learner_id,
                    )
                    ks_status = ks.status
                    next_action = "transfer_verified" if tfng else "mastery_achieved"
                    self._schedule_review(
                        learner_id=sess.learner_id, topic_id=sess.topic_id,
                        session_id=sess.id, trigger_attempt_id=attempt.id,
                        reason="Independent transfer passed; schedule the first delayed retention check.",
                        retention_eligible=True,
                    )

                    if active_diag and active_diag.status == DiagnosticCaseStatus.TRANSFER_CHECKING.value:
                        self.repo.transition_diagnostic_case(
                            active_diag, DiagnosticCaseStatus.RESOLVED,
                            action="transfer_verified", reason="Fresh independent transfer passed; current operational verification only.",
                            uncertainty_note="本次独立迁移验证通过；长期保持尚未验证。",
                        )

        if role == QuestionRole.INITIAL and diag_case_id:
            ks = self.repo.update_knowledge_state(
                session_id=sess.id, topic_id=sess.topic_id, learner_id=sess.learner_id,
                target_status=KnowledgeMasteryStatus.NEEDS_DIAGNOSIS,
                reason="New initial response needs diagnosis; previous verification does not override new contradictory or insufficient evidence.",
            )
            ks_status = ks.status

        if role in (QuestionRole.TARGETED_PRACTICE, QuestionRole.TRANSFER_CHECK) and diag_case_id:
            case = self.repo.get_diagnostic_case(diag_case_id)
            for hypothesis in case.hypotheses if case else []:
                self.repo.record_evidence(
                    hypothesis_id=hypothesis.id, attempt_id=attempt.id,
                    source_type=EvidenceSourceType.PRACTICE_ATTEMPT if role == QuestionRole.TARGETED_PRACTICE else EvidenceSourceType.TRANSFER_ATTEMPT,
                    source_ref=f"attempt:{attempt.id}",
                    relation=EvidenceRelation.CONTRADICTS if attempt.is_correct else EvidenceRelation.NEUTRAL,
                    summary="本次作答通过规则评价。" if attempt.is_correct else "本次作答未通过；单次失败不能区分具体错误假设。",
                    reliability_note="Deterministic rule evaluation; not proof of a unique misconception or long-term retention.",
                )

        if role == QuestionRole.REVIEW:
            assert review_item is not None
            now = self._now()
            review_item.status = ReviewStatus.COMPLETED.value
            review_item.completed_at = now
            review_item.attempt_id = attempt.id
            state = self.repo.get_knowledge_state(sess.learner_id, sess.topic_id)
            if not attempt.is_correct:
                review_item.review_outcome = "failed"
                review_item.retention_verified = False
                if state is not None and state.status in (KnowledgeMasteryStatus.STABLE.value, KnowledgeMasteryStatus.TRANSFER_VERIFIED.value):
                    state = self.repo.update_knowledge_state(
                        session_id=sess.id, topic_id=sess.topic_id, learner_id=sess.learner_id,
                        target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
                        reason="A delayed review answer was incorrect; current independent verification no longer supports stable status.",
                    )
                    ks_status = state.status
                if sess.status != SessionStatus.DIAGNOSING.value:
                    self.repo.transition_session_status(sess, SessionStatus.DIAGNOSING)
                case = self.repo.create_diagnostic_case(
                    session_id=sess.id, trigger_attempt_id=attempt.id,
                    uncertainty_note="Delayed review answer was incorrect; diagnosis is needed before another intervention.",
                )
                diag_case_id = case.id
                self._schedule_review(
                    learner_id=sess.learner_id, topic_id=sess.topic_id, session_id=sess.id,
                    trigger_attempt_id=attempt.id,
                    reason="Review failed; retain a short-interval follow-up while diagnosis proceeds.",
                    retention_eligible=False, hypothesis_id=review_item.hypothesis_id,
                )
                next_action = "review_failed_needs_diagnosis"
            elif (review_item.retention_eligible and state is not None
                    and state.status in (KnowledgeMasteryStatus.STABLE.value, KnowledgeMasteryStatus.TRANSFER_VERIFIED.value)
                    and now >= self._as_utc(review_item.scheduled_for)):
                review_item.review_outcome = "passed_delayed"
                review_item.retention_verified = True
                next_action = "delayed_retention_verified"
                event = self.repo.append_decision_event(
                    session_id=sess.id, event_type="delayed_retention_evaluated",
                    from_state=state.status, to_state=state.status, action="verify_delayed_retention",
                    reason="A due, independently answered review passed; this delayed evidence is not a long-term guarantee.",
                    payload_json={"review_item_id": review_item.id, "attempt_id": attempt.id,
                                  "question_id": question.id, "retention_verified": True,
                                  "knowledge_state_id": review_item.knowledge_state_id,
                                  "scheduled_for": self._as_utc(review_item.scheduled_for).isoformat(),
                                  "submitted_at": now.isoformat(), "review_stage": review_item.review_stage},
                    idempotency_key=f"review-result:{attempt.id}",
                )
                review_item.decision_event_id = event.id
                self.repo.transition_session_status(sess, SessionStatus.COMPLETED)
                self._schedule_review(
                    learner_id=sess.learner_id, topic_id=sess.topic_id, session_id=sess.id,
                    trigger_attempt_id=attempt.id,
                    reason="Delayed review passed; schedule the next spaced retention check.",
                    stage=min(review_item.review_stage + 1, len(self.review_intervals_days) - 1),
                    retention_eligible=True, hypothesis_id=review_item.hypothesis_id,
                )
            else:
                review_item.review_outcome = "passed_without_retention_baseline"
                review_item.retention_verified = False
                next_action = "review_passed_without_retention"
                self.repo.append_decision_event(
                    session_id=sess.id, event_type="review_practice_evaluated",
                    to_state=sess.status, action="review_passed_without_retention",
                    reason="The answer passed, but no valid prior stable state supports a delayed-retention conclusion.",
                    payload_json={"review_item_id": review_item.id, "attempt_id": attempt.id,
                                  "question_id": question.id, "retention_verified": False},
                )
                self.repo.transition_session_status(sess, SessionStatus.COMPLETED)

        result = self._build_attempt_result(
            sess,
            attempt,
            question,
            next_action=next_action,
            diagnostic_case_id=diag_case_id,
            knowledge_state_status=ks_status,
        )
        result_event = self.repo.append_decision_event(
            session_id=sess.id, diagnostic_case_id=diag_case_id,
            event_type="attempt_evaluated", action="record_attempt_result", to_state=sess.status,
            reason="Persist learner-facing evaluation, provenance and original retry response.",
            payload_json={"attempt_id": attempt.id, "evaluation_source": "rule_check", "result": result.model_dump(mode="json")},
        )
        if role == QuestionRole.REVIEW and review_item is not None:
            review_item.decision_event_id = result_event.id
        self.db.commit()
        return result

    def _assigned_reading_group(self, session: LearningSession, question: Question) -> ReadingGroupVersion:
        group = self.db.get(ReadingGroupVersion, session.current_group_version_id) if session.current_group_version_id else None
        current = self.db.get(ReadingGroupVersion, question.reading_group_version_id) if question.reading_group_version_id else None
        if (
            group is None
            or current is None
            or group.exam_variant != session.exam_variant
            or group.group_id != current.group_id
            or group.question_type != current.question_type
            or group.question_type != question.question_type
        ):
            raise DomainRuleViolationError("The assigned reading group version is unavailable or incompatible.")
        return group

    def _submit_reading_group(
        self,
        session: LearningSession,
        question_id: str,
        group_version_id: str | None,
        answers: dict[str, str],
        idempotency_key: str | None,
    ) -> AttemptResultResponse:
        session_id = session.id

        def replay(attempt: Attempt) -> AttemptResultResponse:
            # Dict equality ignores JSON member ordering, unlike legacy text comparison.
            if (
                attempt.session_id != session_id
                or attempt.question_id != question_id
                or attempt.group_version_id != group_version_id
                or attempt.structured_answer_json != answers
            ):
                raise IdempotencyConflictError(idempotency_key or "", "Key belongs to a different answer intent.")
            result = self._stored_attempt_result(session_id, attempt.id)
            if result is None:
                raise ApplicationError("The original group result is unavailable.", code="GROUP_RESULT_UNAVAILABLE", status_code=409)
            return result

        def attempt_by_key() -> Attempt | None:
            if not idempotency_key:
                return None
            return self.db.scalar(select(Attempt).where(Attempt.idempotency_key == idempotency_key))

        existing = attempt_by_key()
        if existing is not None:
            return replay(existing)
        question = self.repo.get_question_by_id(question_id)
        if (
            question is None
            or question.id != session.current_question_id
            or question.topic_id != session.topic_id
            or question.question_type != QuestionType.MATCHING_HEADINGS.value
        ):
            raise DomainRuleViolationError("Submit structured answers only to the assigned Matching Headings question.")
        role = QuestionRole(question.question_role)
        active_status = {
            QuestionRole.INITIAL: SessionStatus.ACTIVE,
            QuestionRole.DIAGNOSTIC_FOLLOWUP: SessionStatus.DIAGNOSING,
            QuestionRole.TARGETED_PRACTICE: SessionStatus.INTERVENING,
        }.get(role)
        if active_status is None:
            raise DomainRuleViolationError("Matching Headings transfer and review are not available yet.")
        if not group_version_id or group_version_id != session.current_group_version_id:
            raise DomainRuleViolationError("The submitted reading group version does not match the assigned version.")
        group = self._assigned_reading_group(session, question)
        rule = self.db.get(ReadingRuleVersion, group.rule_version_id)
        evaluator = evaluator_for_domain(session.topic.domain_code)
        if rule is None or not isinstance(evaluator, IeltsReadingEvaluator):
            raise DomainRuleViolationError("No scoring rule is available for this reading group.")
        try:
            display = MatchingHeadingsGroup.model_validate(group.display_json)
            key = HeadingAnswerKey.model_validate(rule.private_rules_json)
        except ValidationError:
            raise DomainRuleViolationError("The published reading group or its scoring rule is invalid.") from None
        try:
            score = evaluator.evaluate_group(group=display, key=key, answers=answers)
        except ValueError as exc:
            raise DomainRuleViolationError(str(exc)) from exc
        evaluation = ReadingGroupEvaluation(
            **score.model_dump(),
            group_version_id=group.id,
            content_version=group.content_version,
            display_schema_version=group.display_schema_version,
            evaluation_rule_version=rule.rules_version,
            rule_version_id=rule.id,
        )

        # Serialize valid submissions for the same assignment, including requests
        # with different keys. The no-op write takes the row lock (SQLite writer
        # lock) without changing the session's timestamps on a replay.
        claim = self.db.execute(
            update(LearningSession)
            .where(
                LearningSession.id == session_id,
                LearningSession.status == active_status.value,
                LearningSession.current_question_id == question_id,
                LearningSession.current_group_version_id == group_version_id,
            )
            .values(updated_at=LearningSession.updated_at)
            .execution_options(synchronize_session=False)
        )
        existing = attempt_by_key()
        if existing is not None:
            return replay(existing)
        prior = self.db.scalar(select(Attempt).where(
            Attempt.session_id == session_id,
            Attempt.question_id == question_id,
            Attempt.group_version_id == group_version_id,
        ))
        if prior is not None:
            if not idempotency_key and prior.idempotency_key is None and prior.structured_answer_json == answers:
                return replay(prior)
            raise ApplicationError("This reading group has already been submitted.", code="GROUP_ALREADY_SUBMITTED", status_code=409)
        if claim.rowcount != 1:
            raise InvalidSessionOperationError("The reading group assignment is no longer active.")

        protocol = MatchingHeadingsRules(self.repo)
        case = None
        diagnostics = published_rules(self.db, group)
        if role != QuestionRole.INITIAL:
            case = self.repo.latest_diagnostic_case(session_id)
            expected_status, action = {
                QuestionRole.DIAGNOSTIC_FOLLOWUP: (DiagnosticCaseStatus.QUESTION_SELECTED, "select_diagnostic_followup"),
                QuestionRole.TARGETED_PRACTICE: (DiagnosticCaseStatus.INTERVENTION_SELECTED, "assign_targeted_practice"),
            }[role]
            if case is None or case.status != expected_status.value or not supported_protocol(case.trigger_attempt):
                raise InvalidSessionOperationError("The reading group was not authorized for this diagnostic stage.")
            initial_group = self.db.get(ReadingGroupVersion, case.trigger_attempt.group_version_id)
            source = published_rules(self.db, initial_group) if initial_group else None
            dispatch = next((event for event in reversed(case.decision_events)
                             if event.action == action and event.event_type == "diagnostic_case_transition"), None)
            payload = dispatch.payload_json if dispatch else {}
            if (
                source is None
                or payload.get("selected_question_id") != question.id
                or payload.get("group_version_id") != group.id
                or not protocol.compatible_task(session, source, question, group, payload.get("target_error_codes", []))
            ):
                raise DomainRuleViolationError("The diagnostic question does not match its recorded dispatch.")

        summary = f"标题匹配正确 {score.correct_count}/{score.total_count} 项。"
        correct = score.outcome == "correct"
        try:
            attempt = self.repo.record_attempt(
                session_id=session_id,
                question_id=question_id,
                submitted_answer=json.dumps(answers, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                is_correct=correct,
                evaluation_status=AttemptEvaluationStatus.EVALUATED,
                evaluation_summary=summary,
                idempotency_key=idempotency_key,
                submitted_at=self._now(),
                reading_group=group,
                structured_answer=answers,
                item_evaluation=evaluation.model_dump(mode="json"),
                evaluation_rule_version=rule.rules_version,
                diagnostic_protocol=diagnostics.protocol if diagnostics else None,
                diagnostic_version=diagnostics.version if diagnostics else None,
            )
        except IntegrityError:
            self.db.rollback()
            existing = attempt_by_key()
            if existing is None:
                raise
            return replay(existing)
        # The row lock excludes a same-session writer. The repository can
        # still find a key concurrently used in a different session.
        if attempt.session_id != session_id or attempt.question_id != question_id:
            return replay(attempt)

        next_action = "reading_group_scored"
        if role == QuestionRole.INITIAL and not correct:
            next_action = "insufficient_evidence"
            note = "逐项评分仅说明哪些匹配正确。当前没有可用于标题匹配的诊断协议。"
            self.repo.transition_session_status(session, SessionStatus.DIAGNOSING)
            case = self.repo.create_diagnostic_case(
                session_id=session_id, trigger_attempt_id=attempt.id, uncertainty_note=note,
            )
            self.repo.transition_diagnostic_case(
                case, DiagnosticCaseStatus.INITIAL_EVALUATED,
                action="record_reading_group_score", reason=summary,
            )
            if diagnostics and supported_protocol(attempt) and protocol.observe_initial(case, attempt, diagnostics):
                next_action = "diagnose"
            else:
                if diagnostics and supported_protocol(attempt):
                    note = "错选项暂无已审核的原因映射，证据不足。"
                self.repo.transition_diagnostic_case(
                    case, DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
                    action="reading_group_diagnosis_unavailable", reason=note, uncertainty_note=note,
                    uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                )
        elif role == QuestionRole.DIAGNOSTIC_FOLLOWUP:
            protocol.observe_followup(case, attempt, diagnostics)
            next_action = "diagnose"
        elif role == QuestionRole.TARGETED_PRACTICE:
            next_action = "matching_headings_transfer_pending" if correct else "matching_headings_practice_incomplete"
            note = "本次训练通过，仍待独立迁移验证。" if correct else "本次训练未通过，候选原因仍待进一步验证。"
            if correct:
                case.uncertainty_note = note
            else:
                self.repo.transition_diagnostic_case(
                    case, DiagnosticCaseStatus.NEEDS_EVIDENCE, action=next_action, reason=note,
                    uncertainty_note=note, uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                )

        case_id = case.id if case else None
        result = AttemptResultResponse(
            attempt_id=attempt.id, session_id=session_id, question_id=question_id,
            question_role=attempt.attempt_role, is_correct=correct,
            evaluation_summary=summary, feedback_text=summary, next_action=next_action,
            diagnostic_case_id=case_id, group_evaluation=evaluation,
        )
        self.repo.append_decision_event(
            session_id=session_id, diagnostic_case_id=case_id,
            event_type="attempt_evaluated", action="record_attempt_result", to_state=session.status,
            reason="Persist the reading group score and original retry response.",
            uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            payload_json={"attempt_id": attempt.id, "evaluation_source": "rule_check", "result": result.model_dump(mode="json")},
        )
        self.db.commit()
        return result

    def _stored_attempt_result(self, session_id: str, attempt_id: str) -> AttemptResultResponse | None:
        events = self.db.scalars(select(DecisionEvent).where(
            DecisionEvent.session_id == session_id, DecisionEvent.action == "record_attempt_result",
        ))
        for event in events:
            if event.payload_json.get("attempt_id") == attempt_id:
                return AttemptResultResponse.model_validate(event.payload_json["result"])
        return None

    def _build_attempt_result(
        self,
        session: LearningSession,
        attempt: Attempt,
        question: Question,
        next_action: str | None = None,
        diagnostic_case_id: str | None = None,
        knowledge_state_status: str | None = None,
    ) -> AttemptResultResponse:
        """Construct a structured AttemptResultResponse."""
        if next_action is None:
            stored = self._stored_attempt_result(session.id, attempt.id)
            if stored is not None:
                return stored
        next_q_dto = None
        next_question = self.repo.get_question_by_id(session.current_question_id) if session.current_question_id else None
        if next_question:
            next_q_dto = self.sanitize_question(next_question)

        return AttemptResultResponse(
            attempt_id=attempt.id,
            session_id=session.id,
            question_id=question.id,
            question_role=question.question_role,
            is_correct=attempt.is_correct,
            evaluation_summary=attempt.evaluation_summary,
            feedback_text=(
                "回答正确！"
                if attempt.is_correct
                else f"回答与预期不符。{attempt.evaluation_summary or ''}"
            ),
            next_action=next_action or "continue",
            next_question=next_q_dto,
            diagnostic_case_id=diagnostic_case_id,
            knowledge_state_status=knowledge_state_status,
            mastery_note="本次独立迁移验证通过；长期保持尚未验证。" if next_action in ("mastery_achieved", "transfer_verified") else None,
        )

    def list_attempts_for_session(self, session_id: str) -> list[AttemptSummaryResponse]:
        """List all attempts recorded in a session."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        attempts = self.repo.list_attempts_for_session(session_id)
        return [
            AttemptSummaryResponse(
                id=a.id,
                session_id=a.session_id,
                question_id=a.question_id,
                question_role=a.attempt_role,
                submitted_answer=a.submitted_answer,
                structured_answer=a.structured_answer_json,
                group_evaluation=a.item_evaluation_json,
                is_correct=a.is_correct,
                evaluation_status=a.evaluation_status,
                evaluation_summary=a.evaluation_summary,
                submitted_at=a.submitted_at,
            )
            for a in attempts
        ]

    def get_attempt_detail(self, attempt_id: str) -> AttemptDetailResponse:
        """Get full immutable detail of an attempt."""
        att = self.repo.get_attempt(attempt_id)
        if att is None:
            raise EntityNotFoundError("Attempt", attempt_id)

        stored = self._stored_attempt_result(att.session_id, att.id)
        return AttemptDetailResponse(
            id=att.id,
            session_id=att.session_id,
            question_id=att.question_id,
            question_role=att.attempt_role,
            question_version=att.question_version,
            submitted_answer=att.submitted_answer,
            structured_answer=att.structured_answer_json,
            group_evaluation=att.item_evaluation_json,
            is_correct=att.is_correct,
            evaluation_status=att.evaluation_status,
            evaluation_summary=att.evaluation_summary,
            idempotency_key=att.idempotency_key,
            diagnostic_case_id=stored.diagnostic_case_id if stored else None,
            evaluation_source=stored.evaluation_source if stored else None,
            submitted_at=att.submitted_at,
        )

    # -----------------------------------------------------------------------
    # 4. Transfer Check Dispatching
    # -----------------------------------------------------------------------

    def dispatch_transfer_question(
        self,
        session_id: str,
        force_fresh: bool = True,
    ) -> TransferCheckDispatchResponse:
        """Dispatch a fresh, unattempted transfer verification question for the session."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        # Retried dispatches recover the already-assigned question even when
        # force_fresh=True. Never discard an unanswered item to manufacture freshness.
        current = self.repo.get_question_by_id(sess.current_question_id) if sess.current_question_id else None
        history = self.repo.list_attempts_for_session(sess.id)
        if (sess.status == SessionStatus.TRANSFER_CHECKING.value and current
            and current.question_role == QuestionRole.TRANSFER_CHECK.value
            and not any(attempt.question_id == current.id for attempt in history)):
            return TransferCheckDispatchResponse(
                question=self.sanitize_question(current), session_status=SessionStatus(sess.status),
                degraded=False, message="恢复尚未作答的服务端迁移验证题。",
            )
        self.repo.validate_transfer_readiness(sess)
        chosen_q = self._enter_transfer(sess, "Server-authorized independent transfer dispatch.")
        self.db.commit()
        return TransferCheckDispatchResponse(
            question=self.sanitize_question(chosen_q) if chosen_q else None,
            session_status=SessionStatus(sess.status),
            degraded=chosen_q is None,
            message="成功派发独立新情境迁移验证题。" if chosen_q else "暂无未作答过的独立新情境迁移题；证据不足，未确认掌握。",
        )

    # -----------------------------------------------------------------------
    # 5. Reviews & Profile & Dashboard
    # -----------------------------------------------------------------------

    def _review_item_response(self, item: ReviewItem, message: str | None = None) -> ReviewItemResponse:
        question = self.repo.get_question_by_id(item.question_id) if item.question_id else None
        attempt = self.repo.get_attempt(item.attempt_id) if item.attempt_id else None
        return ReviewItemResponse(
            id=item.id, topic_id=item.topic_id, topic_title=item.topic.title,
            session_id=item.session_id, learner_id=item.learner_id,
            trigger_reason=item.trigger_reason, scheduled_for=self._as_utc(item.scheduled_for),
            status=item.status, created_at=self._as_utc(item.created_at),
            completed_at=self._as_utc(item.completed_at) if item.completed_at else None,
            review_stage=item.review_stage, review_session_id=item.review_session_id,
            question_id=item.question_id,
            current_question=self.sanitize_question(question) if question and item.status == ReviewStatus.PENDING.value else None,
            review_question=self.sanitize_question(question) if question else None,
            attempt_id=item.attempt_id, review_outcome=item.review_outcome,
            is_correct=attempt.is_correct if attempt else None,
            submitted_at=self._as_utc(attempt.submitted_at) if attempt else None,
            evaluation_summary=attempt.evaluation_summary if attempt else None,
            retention_verified=item.retention_verified,
            retention_eligible=item.retention_eligible,
            decision_event_id=item.decision_event_id, message=message,
            is_due=(item.status == ReviewStatus.PENDING.value
                    and self._now() >= self._as_utc(item.scheduled_for)),
            knowledge_state_id=item.knowledge_state_id,
        )

    def list_reviews(
        self,
        learner_id: str = "default_learner",
        status: str = "pending",
    ) -> list[ReviewItemResponse]:
        reviews = self.repo.list_review_items_for_learner(learner_id=learner_id, status=status)
        return [self._review_item_response(item) for item in reviews]

    def get_review(self, review_id: str, learner_id: str) -> ReviewItemResponse:
        item = self.repo.get_review_item(review_id)
        if item is None or item.learner_id != learner_id:
            raise EntityNotFoundError("ReviewItem", review_id)
        return self._review_item_response(item)

    def start_review(self, review_id: str, learner_id: str) -> ReviewItemResponse:
        item = self.repo.get_review_item(review_id)
        if item is None or item.learner_id != learner_id:
            raise EntityNotFoundError("ReviewItem", review_id)
        if item.status != ReviewStatus.PENDING.value:
            raise DomainRuleViolationError("This review task has already been completed and cannot be started again.")
        if self._now() < self._as_utc(item.scheduled_for):
            raise DomainRuleViolationError("This review task is not due yet.")
        if item.review_session_id:
            return self._review_item_response(item, "恢复已派发的复习题；请继续提交作答。")

        question = self.repo.next_review_question(item)
        if question is None:
            if not item.session_id:
                self.db.commit()
                return self._review_item_response(item, "题库中没有未作答且情境不同的复习题。任务仍保留待办，不会记为通过。")
            event = self.repo.append_decision_event(
                session_id=item.session_id, event_type="review_question_unavailable",
                to_state=ReviewStatus.PENDING.value, action="review_question_pool_exhausted",
                reason="No eligible unattempted review question is available; keep the review task pending.",
                payload_json={"review_item_id": item.id, "topic_id": item.topic_id,
                              "learner_id": item.learner_id, "retention_verified": False},
                idempotency_key=f"review-empty:{item.id}",
            )
            item.decision_event_id = event.id
            self.db.commit()
            return self._review_item_response(item, "题库中没有未作答且情境不同的复习题。任务仍保留待办，不会记为通过。")

        try:
            source_session = self.repo.get_session(item.session_id) if item.session_id else None
            review_session = self.repo.create_session(
                topic_id=item.topic_id, learner_id=item.learner_id,
                current_question_id=question.id, status=SessionStatus.REVIEWING,
                exam_variant=source_session.exam_variant if source_session else None,
                exam_spec_version=source_session.exam_spec_version if source_session else None,
            )
            claim = self.db.execute(
                update(ReviewItem)
                .where(
                    ReviewItem.id == item.id,
                    ReviewItem.learner_id == learner_id,
                    ReviewItem.status == ReviewStatus.PENDING.value,
                    ReviewItem.review_session_id.is_(None),
                )
                .values(review_session_id=review_session.id, question_id=question.id)
            )
            if claim.rowcount != 1:
                self.db.rollback()
                restored = self.repo.get_review_item(review_id)
                if restored and restored.learner_id == learner_id and restored.review_session_id:
                    return self._review_item_response(restored, "另一请求已派发复习题；已恢复该服务端任务。")
                raise DomainRuleViolationError("This review task changed while the question was being dispatched.")
            item.review_session_id = review_session.id
            item.question_id = question.id
            dispatch_event = self.repo.append_decision_event(
                session_id=review_session.id, event_type="review_question_dispatched",
                to_state=review_session.status, action="dispatch_review_question",
                reason="Dispatch an unseen review question for this due review task.",
                payload_json={"review_item_id": item.id, "question_id": question.id,
                              "source_session_id": item.session_id, "review_stage": item.review_stage,
                              "scheduled_for": self._as_utc(item.scheduled_for).isoformat()},
                idempotency_key=f"review-dispatch:{item.id}",
            )
            if item.decision_event_id is None:
                item.decision_event_id = dispatch_event.id
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            restored = self.repo.get_review_item(review_id)
            if restored and restored.learner_id == learner_id and restored.review_session_id:
                return self._review_item_response(restored, "另一请求已派发复习题；已恢复该服务端任务。")
            raise
        return self._review_item_response(item, "已派发服务端复习题；延迟保持需以提交作答后的评价为准。")

    def complete_review(
        self,
        review_id: str,
        review_notes: str | None = None,
    ) -> ReviewItemResponse:
        item = self.repo.get_review_item(review_id)
        if item is None:
            raise EntityNotFoundError("ReviewItem", review_id)
        raise DomainRuleViolationError(
            "A review cannot be completed by acknowledgment alone. Start the due task and submit its assigned answer."
        )

    def list_knowledge_states(
        self,
        learner_id: str = "default_learner",
    ) -> list[KnowledgeStateResponse]:
        """List current knowledge mastery states for a learner."""
        states = self.repo.list_knowledge_states_for_learner(learner_id)
        hypotheses_by_topic_and_code: dict[tuple[str, str], list[Hypothesis]] = {}
        learner_hypotheses = self.db.scalars(
            select(Hypothesis)
            .join(DiagnosticCase, Hypothesis.diagnostic_case_id == DiagnosticCase.id)
            .join(LearningSession, DiagnosticCase.session_id == LearningSession.id)
            .where(LearningSession.learner_id == learner_id)
            .order_by(Hypothesis.updated_at.desc())
        ).all()
        for hypothesis in learner_hypotheses:
            topic_id = hypothesis.diagnostic_case.topic_id
            hypotheses_by_topic_and_code.setdefault((topic_id, hypothesis.error_code), []).append(hypothesis)
        responses: list[KnowledgeStateResponse] = []
        for ks in states:
            reviews = self.db.scalars(
                select(ReviewItem)
                .where(ReviewItem.knowledge_state_id == ks.id)
                .order_by(ReviewItem.created_at.desc())
            ).all()
            pending_retention = any(
                item.status == ReviewStatus.PENDING.value and item.retention_eligible
                for item in reviews
            )
            completed_reviews = [item for item in reviews if item.attempt_id is not None]
            latest_review = max(
                completed_reviews,
                key=lambda item: self._as_utc(item.completed_at or item.created_at),
                default=None,
            )
            verified_reviews = [item for item in reviews if item.retention_verified]
            latest_verified_review = max(
                verified_reviews,
                key=lambda item: self._as_utc(item.completed_at or item.created_at),
                default=None,
            )
            if latest_review and latest_review.review_outcome == "failed":
                retention_status = "review_failed"
            elif latest_review and latest_review.retention_verified:
                retention_status = "delayed_check_passed"
            elif pending_retention:
                retention_status = "review_due"
            elif any(item.retention_verified for item in reviews):
                retention_status = "delayed_check_passed"
            else:
                retention_status = "not_verified"
            responses.append(KnowledgeStateResponse(
                id=ks.id,
                learner_id=ks.learner_id,
                topic_id=ks.topic_id,
                topic_title=ks.topic.title,
                topic_slug=ks.topic.slug,
                status=KnowledgeMasteryStatus(ks.status),
                confidence_is_heuristic=True,
                unresolved_error_codes=list(ks.unresolved_error_codes or []),
                unresolved_error_reasons=[
                    UnresolvedErrorReasonResponse(
                        title=hypothesis.name,
                        summary=hypothesis.description,
                        status=hypothesis.status,
                    )
                    for error_code in (ks.unresolved_error_codes or [])
                    for hypothesis in hypotheses_by_topic_and_code.get((ks.topic_id, error_code), [])[:1]
                    if hypothesis.status != HypothesisStatus.RULED_OUT.value
                ],
                transition_reason=ks.transition_reason,
                last_transfer_attempt_id=ks.last_transfer_attempt_id,
                updated_at=ks.updated_at,
                retention_status=retention_status,
                retention_evidence_count=sum(1 for item in reviews if item.retention_verified),
                last_reviewed_at=(
                    self._as_utc(latest_review.completed_at)
                    if latest_review and latest_review.completed_at else None
                ),
                last_retention_verified_at=(
                    self._as_utc(latest_verified_review.completed_at)
                    if latest_verified_review and latest_verified_review.completed_at else None
                ),
            ))
        return responses

    def list_learning_history(
        self, learner_id: str = "default_learner", limit: int = 100,
    ) -> list[LearningHistoryEventResponse]:
        """Return a learner-safe timeline assembled from persisted domain records.

        This intentionally projects a small allowlist of event summaries. Raw answers,
        evaluator rules, model prompts, and arbitrary DecisionEvent payloads are never returned.
        """
        sessions = self.repo.list_sessions_for_learner(learner_id)
        session_ids = [session.id for session in sessions]
        if not session_ids:
            return []
        events: list[LearningHistoryEventResponse] = []
        cases = self.db.scalars(
            select(DiagnosticCase)
            .join(LearningSession, DiagnosticCase.session_id == LearningSession.id)
            .where(LearningSession.learner_id == learner_id)
        ).all()
        diagnostic_trigger_attempt_ids = {case.trigger_attempt_id for case in cases}

        def add_event(
            *, event_id: str, kind: str, occurred_at: datetime, topic_id: str,
            topic_title: str, title: str, summary: str, evidence_summary: str,
            session_id: str | None = None, attempt_id: str | None = None,
            review_id: str | None = None,
        ) -> None:
            events.append(LearningHistoryEventResponse(
                id=event_id, kind=kind, occurred_at=self._as_utc(occurred_at),
                topic_id=topic_id, topic_title=topic_title, title=title,
                summary=summary, evidence_summary=evidence_summary,
                session_id=session_id, attempt_id=attempt_id, review_id=review_id,
            ))

        attempts = self.db.scalars(
            select(Attempt)
            .join(LearningSession, Attempt.session_id == LearningSession.id)
            .where(LearningSession.learner_id == learner_id)
        ).all()
        review_items = self.db.scalars(
            select(ReviewItem).where(ReviewItem.learner_id == learner_id)
        ).all()
        review_by_attempt = {item.attempt_id: item for item in review_items if item.attempt_id}
        role_labels = {
            QuestionRole.INITIAL.value: ("answer", "学习作答"),
            QuestionRole.DIAGNOSTIC_FOLLOWUP.value: ("diagnostic_question", "诊断追问"),
            QuestionRole.TARGETED_PRACTICE.value: ("targeted_practice", "针对性练习"),
            QuestionRole.TRANSFER_CHECK.value: ("transfer_check", "独立迁移验证"),
            QuestionRole.REVIEW.value: ("delayed_review", "延迟复习作答"),
        }
        for attempt in attempts:
            session = self.repo.get_session(attempt.session_id)
            if session is None:
                continue
            kind, label = role_labels.get(attempt.attempt_role, ("answer", "学习作答"))
            passed = attempt.is_correct is True
            result_text = "通过" if passed else "需要继续练习" if attempt.is_correct is False else "评价尚未完成"
            if (attempt.attempt_role == QuestionRole.INITIAL.value
                    and (not passed or attempt.id in diagnostic_trigger_attempt_ids)):
                label, kind = "初次作答", "incorrect_answer"
                result_text = "作答后进入诊断，原因仍需结合后续证据判断。"
            elif attempt.attempt_role == QuestionRole.REVIEW.value:
                label = "延迟复习作答"
                result_text = "获得一次延迟复习证据。" if passed else "本次复习未通过，需要继续学习。"
            add_event(
                event_id=f"attempt:{attempt.id}", kind=kind,
                occurred_at=attempt.submitted_at, topic_id=session.topic_id,
                topic_title=session.topic.title, title=label, summary=result_text,
                evidence_summary=f"服务端作答记录 · {attempt.id} · 评价状态 {attempt.evaluation_status}",
                session_id=session.id, attempt_id=attempt.id,
                review_id=(review_by_attempt[attempt.id].id if attempt.id in review_by_attempt else None),
            )

        for case in cases:
            topic = self.repo.get_topic_by_id(case.topic_id)
            if topic is None:
                continue
            add_event(
                event_id=f"diagnosis:{case.id}", kind="diagnosis",
                occurred_at=case.created_at, topic_id=case.topic_id,
                topic_title=topic.title, title="开始错误诊断",
                summary="系统保留了多个可能原因，并根据后续作答继续收集证据。",
                evidence_summary=f"诊断案例 {case.id} · 触发作答 {case.trigger_attempt_id}",
                session_id=case.session_id, attempt_id=case.trigger_attempt_id,
            )

        # DecisionEvent is append-only but its payload is internal. Expose only
        # learner-facing event categories and fixed summaries from this allowlist.
        learner_event_copy = {
            "diagnostic_step_completed": ("diagnostic_update", "更新诊断判断", "系统根据新证据更新了可能原因和下一步安排。"),
            "transfer_verified": ("transfer_verified", "迁移验证通过", "新的应用情境验证通过；这表示当前迁移证据，不代表长期保持。"),
            "review_scheduled": ("review_scheduled", "安排后续复习", "系统根据已保存的学习证据安排了后续复习。"),
        }
        decisions = self.db.scalars(
            select(DecisionEvent)
            .where(DecisionEvent.session_id.in_(session_ids))
            .order_by(DecisionEvent.created_at.desc())
        ).all()
        for event in decisions:
            projection = learner_event_copy.get(event.event_type)
            if projection is None:
                continue
            session = self.repo.get_session(event.session_id)
            if session is None:
                continue
            kind, title, summary = projection
            add_event(
                event_id=f"decision:{event.id}", kind=kind,
                occurred_at=event.created_at, topic_id=session.topic_id,
                topic_title=session.topic.title, title=title, summary=summary,
                evidence_summary=f"服务端决策记录 · {event.id} · 不含内部提示词或执行载荷",
                session_id=session.id,
            )

        return sorted(events, key=lambda item: item.occurred_at, reverse=True)[:max(1, min(limit, 200))]

    def get_dashboard_summary(
        self,
        learner_id: str = "default_learner",
    ) -> DashboardSummaryResponse:
        """Provide aggregated metrics and recent activity for the learner dashboard."""
        sessions = self.repo.list_sessions_for_learner(learner_id)
        reviews = self.repo.list_review_items_for_learner(learner_id, status=ReviewStatus.PENDING.value)
        k_states = self.repo.list_knowledge_states_for_learner(learner_id)

        attempts_count = (
            self.db.scalar(
                select(Attempt.id)
                .join(LearningSession, Attempt.session_id == LearningSession.id)
                .where(LearningSession.learner_id == learner_id)
            )
            or 0
        )
        # Total attempts count query
        total_att = len(
            self.db.scalars(
                select(Attempt.id)
                .join(LearningSession, Attempt.session_id == LearningSession.id)
                .where(LearningSession.learner_id == learner_id)
            ).all()
        )

        active_s = sum(
            1
            for s in sessions
            if s.status in ("active", "diagnosing", "intervening", "transfer_checking", "reviewing")
        )
        comp_s = sum(1 for s in sessions if s.status == "completed")
        mastered_topics = sum(1 for ks in k_states if ks.status == KnowledgeMasteryStatus.STABLE.value)
        needs_practice_topics = sum(1 for ks in k_states if ks.status == KnowledgeMasteryStatus.NEEDS_PRACTICE.value)

        recent_sessions_dto: list[SessionSummaryResponse] = []
        for s in sessions[:5]:
            ks_status, topic_mastered = self._resolve_knowledge_state_fields(
                s.learner_id, s.topic_id
            )
            recent_sessions_dto.append(
                SessionSummaryResponse(
                    id=s.id,
                    topic_id=s.topic_id,
                    topic_title=s.topic.title,
                    learner_id=s.learner_id,
                    status=SessionStatus(s.status),
                    knowledge_state_status=ks_status,
                    topic_mastered=topic_mastered,
                    current_question_id=s.current_question_id,
                    attempts_count=len(s.attempts),
                    started_at=s.started_at,
                    updated_at=s.updated_at,
                    completed_at=s.completed_at,
                )
            )
        pending_reviews_dto = [
            ReviewItemResponse(
                id=r.id,
                topic_id=r.topic_id,
                topic_title=r.topic.title,
                session_id=r.session_id,
                learner_id=r.learner_id,
                trigger_reason=r.trigger_reason,
                scheduled_for=r.scheduled_for,
                status=r.status,
                created_at=r.created_at,
                completed_at=r.completed_at,
            )
            for r in reviews[:5]
        ]

        return DashboardSummaryResponse(
            learner_id=learner_id,
            total_sessions=len(sessions),
            active_sessions=active_s,
            completed_sessions=comp_s,
            total_attempts=total_att,
            pending_reviews_count=len(reviews),
            mastered_topics_count=mastered_topics,
            needs_practice_topics_count=needs_practice_topics,
            recent_sessions=recent_sessions_dto,
            pending_reviews=pending_reviews_dto,
        )
