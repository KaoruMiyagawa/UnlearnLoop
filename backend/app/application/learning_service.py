"""Application service orchestrating learning topics, sessions, attempts, and reviews."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    AttemptDetailResponse,
    AttemptResultResponse,
    AttemptSummaryResponse,
    DashboardSummaryResponse,
    KnowledgeStateResponse,
    LearningMaterialResponse,
    ReviewItemResponse,
    SanitizedQuestionResponse,
    SessionDetailResponse,
    SessionSummaryResponse,
    TopicDetailResponse,
    TopicPrerequisiteSummary,
    TopicSummaryResponse,
    TransferCheckDispatchResponse,
)
from app.application.exceptions import (
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
)
from app.domain.exceptions import (
    DomainRuleViolationError,
    InvalidStateTransitionError,
    UnverifiedMasteryError,
)
from app.domain.rules import validate_mastery_transition, validate_session_transition
from app.evaluation.rule_evaluator import RuleEvaluator
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    KnowledgeState,
    KnowledgeTopic,
    LearningMaterial,
    LearningSession,
    Question,
    ReviewItem,
)
from app.persistence.repositories import LearningRepository


class LearningAppService:
    """Coordinates core learning use cases with explicit transaction boundaries."""

    def __init__(self, db_session: Session) -> None:
        self.db = db_session
        self.repo = LearningRepository(db_session)
        self.rule_evaluator = RuleEvaluator()

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
            for m in topic.materials
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
            selected_q_id = init_q.id
        else:
            initial_qs = self.repo.list_questions_for_topic(
                topic.id, role=QuestionRole.INITIAL
            )
            if not initial_qs:
                raise DomainRuleViolationError(
                    f"Topic '{topic.slug}' has no initial questions configured."
                )
            selected_q_id = initial_qs[0].id

        learning_session = self.repo.create_session(
            topic_id=topic.id,
            learner_id=learner_id,
            current_question_id=selected_q_id,
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

    def _select_fresh_transfer_question(
        self, topic_id: str, learner_id: str
    ) -> Question | None:
        """Select the first unattempted transfer_check question for a learner and topic."""
        transfer_qs = self.repo.list_questions_for_topic(
            topic_id, role=QuestionRole.TRANSFER_CHECK
        )
        if not transfer_qs:
            return None
        attempted_q_ids = set(
            self.db.scalars(
                select(Attempt.question_id)
                .join(LearningSession, Attempt.session_id == LearningSession.id)
                .where(
                    LearningSession.learner_id == learner_id,
                    Attempt.attempt_role == QuestionRole.TRANSFER_CHECK.value,
                )
            ).all()
        )
        fresh_qs = [q for q in transfer_qs if q.id not in attempted_q_ids]
        return fresh_qs[0] if fresh_qs else None

    def get_session_detail(self, session_id: str) -> SessionDetailResponse:
        """Fetch session detail including current sanitized question, diagnostic case pointer, and mastery status."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        current_q_dto = None
        if sess.current_question:
            current_q_dto = self.sanitize_question(sess.current_question)

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

        return SessionDetailResponse(
            id=sess.id,
            topic_id=sess.topic_id,
            topic_title=sess.topic.title,
            learner_id=sess.learner_id,
            status=SessionStatus(sess.status),
            knowledge_state_status=ks_status,
            topic_mastered=topic_mastered,
            current_question_id=sess.current_question_id,
            current_question=current_q_dto,
            active_diagnostic_case_id=active_diag.id if active_diag else None,
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
        if ks is None or ks.status != KnowledgeMasteryStatus.STABLE.value:
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
        submitted_answer: str,
        idempotency_key: str | None = None,
    ) -> AttemptResultResponse:
        """Record and evaluate a user attempt, updating diagnostic and mastery states."""
        sess = self.repo.get_session(session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", session_id)

        if sess.status in (SessionStatus.PAUSED.value, SessionStatus.COMPLETED.value):
            raise InvalidSessionOperationError(
                f"Cannot submit answers while session is in '{sess.status}' status.",
                current_state=sess.status,
            )

        question = self.repo.get_question_by_id(question_id)
        if question is None:
            raise EntityNotFoundError("Question", question_id)

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
                        Attempt.session_id == sess.id,
                        Attempt.idempotency_key == idempotency_key,
                    )
                ).first()
            )
            if existing_attempt is not None:
                if (
                    existing_attempt.question_id != question.id
                    or existing_attempt.submitted_answer != submitted_answer
                ):
                    raise IdempotencyConflictError(
                        idempotency_key,
                        "Idempotency key was already used with a different question_id or submitted_answer.",
                    )
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
        }
        if sess.status not in allowed_statuses_by_role.get(role, set()):
            raise InvalidSessionOperationError(
                f"Cannot submit question '{question.id}' with role '{role.value}' "
                f"while session is in '{sess.status}' stage.",
                current_state=sess.status,
            )

        # 5. Same-question retry guardrails:
        #    - For diagnostic_followup: once answered in the current diagnostic turn, require an Agent step before another attempt.
        #    - For transfer_check: if already answered correctly in this session, forbid redundant re-submissions.
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
        attempt = self.repo.record_attempt(
            session_id=sess.id,
            question_id=question.id,
            submitted_answer=submitted_answer,
            evaluation_status=AttemptEvaluationStatus.PENDING,
            idempotency_key=idempotency_key,
        )

        # Run local rule pre-evaluator
        rule_res = self.rule_evaluator.evaluate_attempt(
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
                    if sess.status != SessionStatus.TRANSFER_CHECKING.value:
                        self.repo.transition_session_status(sess, SessionStatus.TRANSFER_CHECKING)
                    fresh_transfer = self._select_fresh_transfer_question(
                        sess.topic_id, sess.learner_id
                    )
                    if fresh_transfer is not None:
                        sess.current_question_id = fresh_transfer.id
                    next_action = "transfer_check"

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
            if attempt.is_correct:
                if sess.status != SessionStatus.TRANSFER_CHECKING.value:
                    self.repo.transition_session_status(sess, SessionStatus.TRANSFER_CHECKING)
                fresh_transfer = self._select_fresh_transfer_question(
                    sess.topic_id, sess.learner_id
                )
                if fresh_transfer is not None:
                    sess.current_question_id = fresh_transfer.id
                next_action = "transfer_check"
            else:
                next_action = "review_scheduled"
                self.repo.schedule_review_item(
                    topic_id=sess.topic_id,
                    session_id=sess.id,
                    learner_id=sess.learner_id,
                    trigger_reason=f"Targeted practice for '{question.id}' failed.",
                )

        elif role == QuestionRole.TRANSFER_CHECK:
            if not attempt.is_correct:
                # Transfer check failed: schedule review and retain needs_practice
                self.repo.schedule_review_item(
                    topic_id=sess.topic_id,
                    session_id=sess.id,
                    learner_id=sess.learner_id,
                    trigger_reason=f"Transfer verification question '{question.id}' failed.",
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
                    ks = self.repo.update_knowledge_state(
                        session_id=sess.id,
                        topic_id=sess.topic_id,
                        target_status=KnowledgeMasteryStatus.STABLE,
                        reason=f"Passed independent fresh transfer verification '{question.id}'.",
                        transfer_attempt_id=attempt.id,
                        learner_id=sess.learner_id,
                    )
                    ks_status = ks.status
                    next_action = "mastery_achieved"

        self.db.commit()
        return self._build_attempt_result(
            sess,
            attempt,
            question,
            next_action=next_action,
            diagnostic_case_id=diag_case_id,
            knowledge_state_status=ks_status,
        )

    def _build_attempt_result(
        self,
        session: LearningSession,
        attempt: Attempt,
        question: Question,
        next_action: str = "continue",
        diagnostic_case_id: str | None = None,
        knowledge_state_status: str | None = None,
    ) -> AttemptResultResponse:
        """Construct a structured AttemptResultResponse."""
        next_q_dto = None
        if session.current_question:
            next_q_dto = self.sanitize_question(session.current_question)

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
            next_action=next_action,
            next_question=next_q_dto,
            diagnostic_case_id=diagnostic_case_id,
            knowledge_state_status=knowledge_state_status,
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

        return AttemptDetailResponse(
            id=att.id,
            session_id=att.session_id,
            question_id=att.question_id,
            question_role=att.attempt_role,
            question_version=att.question_version,
            submitted_answer=att.submitted_answer,
            is_correct=att.is_correct,
            evaluation_status=att.evaluation_status,
            evaluation_summary=att.evaluation_summary,
            idempotency_key=att.idempotency_key,
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

        transfer_qs = self.repo.list_questions_for_topic(
            sess.topic_id, role=QuestionRole.TRANSFER_CHECK
        )
        if not transfer_qs:
            raise DomainRuleViolationError(
                f"No transfer_check questions found for topic '{sess.topic.slug}'."
            )

        # Enforce Stage 3 principle: Prioritize unattempted transfer questions
        attempted_q_ids = set(
            self.db.scalars(
                select(Attempt.question_id)
                .join(LearningSession, Attempt.session_id == LearningSession.id)
                .where(
                    LearningSession.learner_id == sess.learner_id,
                    Attempt.attempt_role == QuestionRole.TRANSFER_CHECK.value,
                )
            ).all()
        )
        fresh_qs = [q for q in transfer_qs if q.id not in attempted_q_ids]

        if not fresh_qs:
            # Safe degradation: do not recycle attempted questions, schedule review and record exhaustion event
            msg = (
                f"知识点 '{sess.topic.slug}' 暂无未作答过的独立新情境迁移验证题；"
                "保留待练习状态并安排复习巩固，防止同题重复猜测造成虚假掌握。"
            )
            if sess.status != SessionStatus.TRANSFER_CHECKING.value:
                self.repo.transition_session_status(sess, SessionStatus.TRANSFER_CHECKING)
            self.repo.update_knowledge_state(
                session_id=sess.id,
                topic_id=sess.topic_id,
                target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
                reason=msg,
                learner_id=sess.learner_id,
            )
            self.repo.schedule_review_item(
                topic_id=sess.topic_id,
                session_id=sess.id,
                learner_id=sess.learner_id,
                trigger_reason=msg,
            )
            self.repo.append_decision_event(
                session_id=sess.id,
                event_type="transfer_questions_exhausted",
                from_state=sess.status,
                to_state=sess.status,
                action="transfer_questions_exhausted",
                reason=msg,
            )
            self.db.commit()
            return TransferCheckDispatchResponse(
                question=None,
                session_status=SessionStatus(sess.status),
                degraded=True,
                message=msg,
            )

        chosen_q = fresh_qs[0]
        sess.current_question_id = chosen_q.id
        if sess.status != SessionStatus.TRANSFER_CHECKING.value:
            self.repo.transition_session_status(sess, SessionStatus.TRANSFER_CHECKING)
        self.db.commit()

        return TransferCheckDispatchResponse(
            question=self.sanitize_question(chosen_q),
            session_status=SessionStatus(sess.status),
            degraded=False,
            message="成功派发独立新情境迁移验证题。",
        )

    # -----------------------------------------------------------------------
    # 5. Reviews & Profile & Dashboard
    # -----------------------------------------------------------------------

    def list_reviews(
        self,
        learner_id: str = "default_learner",
        status: str = "pending",
    ) -> list[ReviewItemResponse]:
        """List scheduled review tasks for a learner."""
        reviews = self.repo.list_review_items_for_learner(
            learner_id=learner_id, status=status
        )
        return [
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
            for r in reviews
        ]

    def complete_review(
        self,
        review_id: str,
        review_notes: str | None = None,
    ) -> ReviewItemResponse:
        """Mark a scheduled review task as completed."""
        r = self.repo.complete_review_item(review_id, review_notes=review_notes)
        self.db.commit()
        return ReviewItemResponse(
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

    def list_knowledge_states(
        self,
        learner_id: str = "default_learner",
    ) -> list[KnowledgeStateResponse]:
        """List current knowledge mastery states for a learner."""
        states = self.repo.list_knowledge_states_for_learner(learner_id)
        return [
            KnowledgeStateResponse(
                id=ks.id,
                learner_id=ks.learner_id,
                topic_id=ks.topic_id,
                topic_title=ks.topic.title,
                topic_slug=ks.topic.slug,
                status=KnowledgeMasteryStatus(ks.status),
                confidence_is_heuristic=True,
                unresolved_error_codes=list(ks.unresolved_error_codes or []),
                transition_reason=ks.transition_reason,
                last_transfer_attempt_id=ks.last_transfer_attempt_id,
                updated_at=ks.updated_at,
            )
            for ks in states
        ]

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
            if s.status in ("active", "diagnosing", "intervening", "transfer_checking")
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
