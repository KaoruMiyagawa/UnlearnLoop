"""Repository and domain persistence operations enforcing Stage 2 invariants."""

from datetime import datetime
import hashlib
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domain.enums import (
    AttemptEvaluationStatus,
    DiagnosticCaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    KnowledgeMasteryStatus,
    ModelCallStatus,
    QuestionRole,
    ReviewStatus,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.exceptions import DomainRuleViolationError
from app.domain.rules import (
    transfer_context_key,
    validate_transfer_entry,
    validate_confidence,
    validate_diagnostic_case_transition,
    validate_hypothesis_transition,
    validate_mastery_transition,
    validate_session_transition,
)
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    EvidenceLink,
    Hypothesis,
    KnowledgeState,
    KnowledgeTopic,
    LearningSession,
    ModelCall,
    Question,
    ReviewItem,
    utc_now,
)


class LearningRepository:
    """Data access and domain-invariant enforcement for the Stage 2 persistence layer."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _reading_material_fingerprint(question: Question) -> str | None:
        if not question.material or not question.material.content_body.strip():
            return None
        normalized = " ".join(question.material.content_body.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _attempt_material_fingerprint(self, attempt: Attempt) -> str | None:
        snapshot = attempt.question_snapshot_json or {}
        return snapshot.get("material_fingerprint") or self._reading_material_fingerprint(attempt.question)

    def _assigned_reading_materials(self, learner_id: str, topic_id: str, *, exclude_session_id: str | None = None) -> set[str | None]:
        statement = select(Question).join(LearningSession, LearningSession.current_question_id == Question.id).where(
            LearningSession.learner_id == learner_id, LearningSession.topic_id == topic_id,
        )
        if exclude_session_id is not None:
            statement = statement.where(LearningSession.id != exclude_session_id)
        return {self._reading_material_fingerprint(question) for question in self.session.scalars(statement)}

    # ------------------------------------------------------------------
    # Topics & Questions
    # ------------------------------------------------------------------

    def list_topics(self, domain_code: str | None = None) -> list[KnowledgeTopic]:
        stmt = select(KnowledgeTopic).order_by(
            KnowledgeTopic.difficulty_level, KnowledgeTopic.slug
        )
        if domain_code:
            stmt = stmt.where(KnowledgeTopic.domain_code == domain_code)
        return list(self.session.scalars(stmt).all())

    def get_topic_by_id(self, topic_id: str) -> KnowledgeTopic | None:
        return self.session.get(KnowledgeTopic, topic_id)

    def get_topic_by_slug(self, slug: str) -> KnowledgeTopic | None:
        stmt = select(KnowledgeTopic).where(KnowledgeTopic.slug == slug)
        return self.session.scalar(stmt)

    def list_questions_for_topic(
        self,
        topic_id: str,
        role: QuestionRole | str | None = None,
    ) -> list[Question]:
        stmt = (
            select(Question)
            .where(Question.topic_id == topic_id)
            .order_by(Question.difficulty, Question.id)
        )
        if role is not None:
            role_val = QuestionRole(role).value
            stmt = stmt.where(Question.question_role == role_val)
        return list(self.session.scalars(stmt).all())

    def get_question_by_id(self, question_id: str) -> Question | None:
        return self.session.get(Question, question_id)

    def get_session(self, session_id: str) -> LearningSession | None:
        return self.session.get(LearningSession, session_id)

    def list_sessions_for_learner(
        self,
        learner_id: str = "local_default_learner",
    ) -> list[LearningSession]:
        stmt = (
            select(LearningSession)
            .where(LearningSession.learner_id == learner_id)
            .order_by(LearningSession.started_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_attempt(self, attempt_id: str) -> Attempt | None:
        return self.session.get(Attempt, attempt_id)

    def list_attempts_for_session(self, session_id: str) -> list[Attempt]:
        stmt = (
            select(Attempt)
            .where(Attempt.session_id == session_id)
            .order_by(Attempt.submitted_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def get_diagnostic_case(self, case_id: str) -> DiagnosticCase | None:
        return self.session.get(DiagnosticCase, case_id)

    def list_evidence_for_case(self, case_id: str) -> list[EvidenceLink]:
        stmt = (
            select(EvidenceLink)
            .join(Hypothesis, EvidenceLink.hypothesis_id == Hypothesis.id)
            .where(Hypothesis.diagnostic_case_id == case_id)
            .order_by(EvidenceLink.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_review_items_for_learner(
        self,
        learner_id: str = "local_default_learner",
        status: str | None = None,
    ) -> list[ReviewItem]:
        stmt = (
            select(ReviewItem)
            .where(ReviewItem.learner_id == learner_id)
            .order_by(ReviewItem.scheduled_for.asc())
        )
        if status:
            stmt = stmt.where(ReviewItem.status == status)
        return list(self.session.scalars(stmt).all())

    def get_review_item(self, review_id: str) -> ReviewItem | None:
        return self.session.get(ReviewItem, review_id)

    def get_review_item_for_session(self, review_session_id: str) -> ReviewItem | None:
        return self.session.scalar(
            select(ReviewItem).where(ReviewItem.review_session_id == review_session_id)
        )

    def cancel_pending_review_items(
        self, *, learner_id: str, topic_id: str, except_schedule_key: str,
    ) -> list[ReviewItem]:
        items = self.session.scalars(
            select(ReviewItem).where(
                ReviewItem.learner_id == learner_id,
                ReviewItem.topic_id == topic_id,
                ReviewItem.status == ReviewStatus.PENDING.value,
                or_(ReviewItem.schedule_key.is_(None), ReviewItem.schedule_key != except_schedule_key),
            )
        ).all()
        for item in items:
            item.status = ReviewStatus.CANCELLED.value
            item.review_outcome = "superseded_by_new_independent_transfer"
        self.session.flush()
        return list(items)

    def next_review_question(self, item: ReviewItem) -> Question | None:
        """Choose an unattempted review question with a context unseen by this learner."""
        candidates = self.session.scalars(
            select(Question)
            .where(
                Question.topic_id == item.topic_id,
                Question.question_role == QuestionRole.REVIEW.value,
            )
            .order_by(Question.difficulty, Question.id)
        ).all()
        prior_attempts = self.session.scalars(
            select(Attempt)
            .join(LearningSession, Attempt.session_id == LearningSession.id)
            .where(
                LearningSession.learner_id == item.learner_id,
                LearningSession.topic_id == item.topic_id,
                Attempt.evaluation_status == AttemptEvaluationStatus.EVALUATED.value,
            )
        ).all()
        seen_ids = {attempt.question_id for attempt in prior_attempts}
        seen_contexts = {
            transfer_context_key(
                str(attempt.question_snapshot_json.get("prompt_text", attempt.question.prompt_text)),
                attempt.question_snapshot_json.get("context_snippet", attempt.question.context_snippet),
            )
            for attempt in prior_attempts
        }
        is_reading = item.topic.domain_code in {"ielts_academic", "ielts_general_training"}
        seen_materials = {self._attempt_material_fingerprint(attempt) for attempt in prior_attempts} if is_reading else set()
        if is_reading:
            seen_materials.update(self._assigned_reading_materials(item.learner_id, item.topic_id))
        return next(
            (
                question for question in candidates
                if question.id not in seen_ids
                and transfer_context_key(question.prompt_text, question.context_snippet) not in seen_contexts
                and (not is_reading or (None not in seen_materials and self._reading_material_fingerprint(question) is not None
                     and self._reading_material_fingerprint(question) not in seen_materials))
            ),
            None,
        )

    def complete_review_item(
        self,
        review_id: str,
        *,
        review_notes: str | None = None,
    ) -> ReviewItem:
        item = self.session.get(ReviewItem, review_id)
        if item is None:
            raise DomainRuleViolationError(f"ReviewItem '{review_id}' not found.")
        raise DomainRuleViolationError(
            "Review completion requires a server-assigned question and evaluated learner attempt."
        )

    def get_knowledge_state(
        self,
        learner_id: str,
        topic_id: str,
    ) -> KnowledgeState | None:
        stmt = select(KnowledgeState).where(
            KnowledgeState.learner_id == learner_id,
            KnowledgeState.topic_id == topic_id,
        )
        return self.session.scalar(stmt)

    def list_knowledge_states_for_learner(
        self,
        learner_id: str = "local_default_learner",
    ) -> list[KnowledgeState]:
        stmt = (
            select(KnowledgeState)
            .where(KnowledgeState.learner_id == learner_id)
            .order_by(KnowledgeState.updated_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # LearningSession & Attempt
    # ------------------------------------------------------------------

    def create_session(
        self,
        *,
        topic_id: str,
        learner_id: str = "local_default_learner",
        current_question_id: str | None = None,
        status: SessionStatus | str = SessionStatus.ACTIVE,
        exam_variant: str | None = None,
        exam_spec_version: str | None = None,
    ) -> LearningSession:
        topic = self.session.get(KnowledgeTopic, topic_id)
        if topic is None:
            raise DomainRuleViolationError(f"Unknown KnowledgeTopic ID: {topic_id}")

        if current_question_id is not None:
            question = self.session.get(Question, current_question_id)
            if question is None or question.topic_id != topic_id:
                raise DomainRuleViolationError(
                    "Session initial question must exist and belong to the session topic."
                )

        learning_session = LearningSession(
            learner_id=learner_id,
            topic_id=topic_id,
            current_question_id=current_question_id,
            status=SessionStatus(status).value,
            exam_variant=exam_variant,
            exam_spec_version=exam_spec_version,
        )
        self.session.add(learning_session)
        self.session.flush()
        return learning_session

    def transition_session_status(
        self,
        learning_session: LearningSession,
        target_status: SessionStatus | str,
    ) -> LearningSession:
        target_enum = SessionStatus(target_status)
        validate_session_transition(learning_session.status, target_enum)
        learning_session.status = target_enum.value
        if target_enum == SessionStatus.COMPLETED:
            learning_session.completed_at = utc_now()
        self.session.flush()
        return learning_session

    def latest_diagnostic_case(self, session_id: str) -> DiagnosticCase | None:
        return self.session.scalars(
            select(DiagnosticCase).where(DiagnosticCase.session_id == session_id)
            .order_by(DiagnosticCase.created_at.desc(), DiagnosticCase.id.desc())
        ).first()

    def fresh_transfer_questions(self, learning_session: LearningSession) -> list[Question]:
        """Exclude previously attempted IDs AND contexts, including renamed copies."""
        attempts = list(self.session.scalars(
            select(Attempt).join(LearningSession, Attempt.session_id == LearningSession.id)
            .where(LearningSession.learner_id == learning_session.learner_id,
                   LearningSession.topic_id == learning_session.topic_id)
        ))
        excluded_ids = {attempt.question_id for attempt in attempts}
        excluded_contexts = {
            transfer_context_key(
                attempt.question_snapshot_json.get("prompt_text", attempt.question.prompt_text),
                attempt.question_snapshot_json.get("context_snippet", attempt.question.context_snippet),
            ) for attempt in attempts
        }
        # Catalog role labels alone do not prove a new situation.
        for question in self.list_questions_for_topic(learning_session.topic_id):
            if question.question_role != QuestionRole.TRANSFER_CHECK.value:
                excluded_contexts.add(transfer_context_key(question.prompt_text, question.context_snippet))
        is_reading = learning_session.topic.domain_code in {"ielts_academic", "ielts_general_training"}
        excluded_materials = {self._attempt_material_fingerprint(attempt) for attempt in attempts} if is_reading else set()
        if is_reading:
            excluded_materials.update(self._assigned_reading_materials(learning_session.learner_id, learning_session.topic_id, exclude_session_id=learning_session.id))
            excluded_materials.update(self._reading_material_fingerprint(q) for q in self.list_questions_for_topic(learning_session.topic_id)
                                      if q.question_role in {QuestionRole.INITIAL.value, QuestionRole.DIAGNOSTIC_FOLLOWUP.value, QuestionRole.TARGETED_PRACTICE.value})
        return [question for question in self.list_questions_for_topic(
            learning_session.topic_id, role=QuestionRole.TRANSFER_CHECK
        ) if question.id not in excluded_ids and transfer_context_key(
            question.prompt_text, question.context_snippet
        ) not in excluded_contexts and (not is_reading or (None not in excluded_materials and self._reading_material_fingerprint(question) is not None
                                and self._reading_material_fingerprint(question) not in excluded_materials))]

    def validate_transfer_readiness(
        self, learning_session: LearningSession, *, agent_selected: bool = False,
    ) -> None:
        attempts = self.list_attempts_for_session(learning_session.id)
        case = self.latest_diagnostic_case(learning_session.id)
        practices = [attempt for attempt in attempts if attempt.attempt_role == QuestionRole.TARGETED_PRACTICE.value]
        validate_transfer_entry(
            learning_session.status,
            has_pending_question=bool(learning_session.current_question_id and not any(
                attempt.question_id == learning_session.current_question_id for attempt in attempts
            )),
            practice_required=bool(practices or (case and case.selected_intervention == "targeted_practice")),
            practice_passed=bool(practices and practices[-1].is_correct is True
                                 and practices[-1].evaluation_status == AttemptEvaluationStatus.EVALUATED.value),
            agent_selected=agent_selected,
        )

    def record_attempt(
        self,
        *,
        session_id: str,
        question_id: str,
        submitted_answer: str,
        is_correct: bool | None = None,
        evaluation_status: AttemptEvaluationStatus | str = AttemptEvaluationStatus.PENDING,
        evaluation_summary: str | None = None,
        idempotency_key: str | None = None,
        submitted_at: datetime | None = None,
    ) -> Attempt:
        """Record an immutable learner attempt linked to its Question and LearningSession."""
        if idempotency_key:
            existing = self.session.scalar(
                select(Attempt).where(Attempt.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing

        learning_session = self.session.get(LearningSession, session_id)
        if learning_session is None:
            raise DomainRuleViolationError(f"Unknown LearningSession ID: {session_id}")

        question = self.session.get(Question, question_id)
        if question is None:
            raise DomainRuleViolationError(f"Unknown Question ID: {question_id}")

        if question.topic_id != learning_session.topic_id:
            raise DomainRuleViolationError(
                f"Question {question_id} belongs to topic {question.topic_id}, "
                f"which does not match session topic {learning_session.topic_id}."
            )

        if not submitted_answer or not submitted_answer.strip():
            raise DomainRuleViolationError("Attempt submitted_answer cannot be empty.")

        eval_status_enum = AttemptEvaluationStatus(evaluation_status)
        question_snapshot = {
            "question_id": question.id,
            "version": question.version,
            "question_role": question.question_role,
            "question_type": question.question_type,
            "prompt_text": question.prompt_text,
            "context_snippet": question.context_snippet,
            "standard_answer": question.standard_answer,
            "material_id": question.material_id,
            "material_fingerprint": self._reading_material_fingerprint(question),
        }
        attempt = Attempt(
            session_id=session_id,
            question_id=question_id,
            question_version=question.version,
            question_snapshot_json=question_snapshot,
            attempt_role=question.question_role,
            submitted_answer=submitted_answer,
            is_correct=is_correct,
            evaluation_status=eval_status_enum.value,
            evaluation_summary=evaluation_summary,
            idempotency_key=idempotency_key,
            submitted_at=submitted_at or utc_now(),
        )
        self.session.add(attempt)
        self.session.flush()
        return attempt

    # ------------------------------------------------------------------
    # DecisionEvent (Append-Only)
    # ------------------------------------------------------------------

    def append_decision_event(
        self,
        *,
        session_id: str,
        event_type: str,
        to_state: str,
        action: str,
        reason: str,
        diagnostic_case_id: str | None = None,
        from_state: str | None = None,
        uncertainty_level: UncertaintyLevel | str = UncertaintyLevel.MEDIUM,
        payload_json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> DecisionEvent:
        """Append an immutable DecisionEvent record."""
        if idempotency_key:
            existing = self.session.scalar(
                select(DecisionEvent).where(
                    DecisionEvent.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing

        if not reason or not reason.strip():
            raise DomainRuleViolationError("DecisionEvent reason must be non-empty.")

        uncertainty_enum = UncertaintyLevel(uncertainty_level)
        evt = DecisionEvent(
            session_id=session_id,
            diagnostic_case_id=diagnostic_case_id,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            action=action,
            reason=reason.strip(),
            uncertainty_level=uncertainty_enum.value,
            payload_json=payload_json or {},
            idempotency_key=idempotency_key,
        )
        self.session.add(evt)
        self.session.flush()
        return evt

    # ------------------------------------------------------------------
    # DiagnosticCase, Competing Hypotheses, & EvidenceLink
    # ------------------------------------------------------------------

    def create_diagnostic_case(
        self,
        *,
        session_id: str,
        trigger_attempt_id: str,
        uncertainty_note: str | None = None,
    ) -> DiagnosticCase:
        attempt = self.session.get(Attempt, trigger_attempt_id)
        if attempt is None or attempt.session_id != session_id:
            raise DomainRuleViolationError(
                "DiagnosticCase trigger_attempt_id must belong to the given session."
            )
        learning_session = self.session.get(LearningSession, session_id)
        if learning_session is None:
            raise DomainRuleViolationError(f"Unknown LearningSession ID: {session_id}")

        diag_case = DiagnosticCase(
            session_id=session_id,
            trigger_attempt_id=trigger_attempt_id,
            topic_id=learning_session.topic_id,
            status=DiagnosticCaseStatus.COLLECTING_ATTEMPT.value,
            uncertainty_note=uncertainty_note,
        )
        self.session.add(diag_case)
        self.session.flush()
        return diag_case

    def transition_diagnostic_case(
        self,
        diag_case: DiagnosticCase,
        target_status: DiagnosticCaseStatus | str,
        *,
        action: str,
        reason: str,
        uncertainty_level: UncertaintyLevel | str = UncertaintyLevel.MEDIUM,
        uncertainty_note: str | None = None,
        selected_intervention: str | None = None,
        payload_json: dict[str, Any] | None = None,
    ) -> DecisionEvent:
        """Validate DiagnosticCase state transition and append a DecisionEvent."""
        target_enum = DiagnosticCaseStatus(target_status)
        previous_status = diag_case.status
        selected_question_answered = False
        if (
            previous_status == DiagnosticCaseStatus.QUESTION_SELECTED.value
            and target_enum == DiagnosticCaseStatus.INTERVENTION_SELECTED
            and diag_case.current_followup_question_id
        ):
            selected_question_answered = any(
                attempt.question_id == diag_case.current_followup_question_id
                for attempt in self.list_attempts_for_session(diag_case.session_id)
            )
        validate_diagnostic_case_transition(
            previous_status,
            target_enum,
            selected_question_answered=selected_question_answered,
        )

        diag_case.status = target_enum.value
        if uncertainty_note is not None:
            diag_case.uncertainty_note = uncertainty_note
        if selected_intervention is not None:
            diag_case.selected_intervention = selected_intervention

        evt = self.append_decision_event(
            session_id=diag_case.session_id,
            diagnostic_case_id=diag_case.id,
            event_type="diagnostic_case_transition",
            from_state=previous_status,
            to_state=target_enum.value,
            action=action,
            reason=reason,
            uncertainty_level=uncertainty_level,
            payload_json=payload_json,
        )
        self.session.flush()
        return evt

    def add_hypothesis(
        self,
        *,
        diagnostic_case_id: str,
        error_code: str,
        name: str,
        description: str,
        confidence: float,
        status: HypothesisStatus | str = HypothesisStatus.CANDIDATE,
        missing_evidence_desc: str | None = None,
    ) -> Hypothesis:
        """Add a candidate error hypothesis to a DiagnosticCase."""
        validate_confidence(confidence)
        status_enum = HypothesisStatus(status)

        diag_case = self.session.get(DiagnosticCase, diagnostic_case_id)
        if diag_case is None:
            raise DomainRuleViolationError(
                f"Unknown DiagnosticCase ID: {diagnostic_case_id}"
            )

        hypothesis = Hypothesis(
            diagnostic_case_id=diagnostic_case_id,
            error_code=error_code.strip(),
            name=name.strip(),
            description=description.strip(),
            confidence=confidence,
            status=status_enum.value,
            missing_evidence_desc=missing_evidence_desc,
        )
        self.session.add(hypothesis)
        self.session.flush()
        return hypothesis

    def update_hypothesis(
        self,
        hypothesis: Hypothesis,
        *,
        new_status: HypothesisStatus | str,
        new_confidence: float,
        reason: str,
        missing_evidence_desc: str | None = None,
    ) -> DecisionEvent:
        """Transition a Hypothesis status/confidence and record a DecisionEvent."""
        validate_confidence(new_confidence)
        target_enum = HypothesisStatus(new_status)
        previous_status = hypothesis.status
        validate_hypothesis_transition(previous_status, target_enum)

        diag_case = self.session.get(DiagnosticCase, hypothesis.diagnostic_case_id)
        if diag_case is None:
            raise DomainRuleViolationError("Parent DiagnosticCase not found.")

        hypothesis.status = target_enum.value
        hypothesis.confidence = new_confidence
        if missing_evidence_desc is not None:
            hypothesis.missing_evidence_desc = missing_evidence_desc

        evt = self.append_decision_event(
            session_id=diag_case.session_id,
            diagnostic_case_id=diag_case.id,
            event_type="hypothesis_updated",
            from_state=previous_status,
            to_state=target_enum.value,
            action="update_hypothesis",
            reason=reason,
            payload_json={
                "hypothesis_id": hypothesis.id,
                "error_code": hypothesis.error_code,
                "new_confidence": new_confidence,
            },
        )
        self.session.flush()
        return evt

    def record_evidence(
        self,
        *,
        hypothesis_id: str,
        source_type: EvidenceSourceType | str,
        source_ref: str,
        relation: EvidenceRelation | str,
        summary: str,
        attempt_id: str | None = None,
        decision_event_id: str | None = None,
        reliability_note: str | None = None,
    ) -> EvidenceLink:
        """Attach an immutable EvidenceLink with mandatory source tracking."""
        if not source_ref or not source_ref.strip():
            raise DomainRuleViolationError("EvidenceLink source_ref cannot be empty.")
        if not summary or not summary.strip():
            raise DomainRuleViolationError("EvidenceLink summary cannot be empty.")

        hypothesis = self.session.get(Hypothesis, hypothesis_id)
        if hypothesis is None:
            raise DomainRuleViolationError(f"Unknown Hypothesis ID: {hypothesis_id}")

        source_enum = EvidenceSourceType(source_type)
        relation_enum = EvidenceRelation(relation)

        evidence = EvidenceLink(
            hypothesis_id=hypothesis_id,
            attempt_id=attempt_id,
            decision_event_id=decision_event_id,
            source_type=source_enum.value,
            source_ref=source_ref.strip(),
            relation=relation_enum.value,
            summary=summary.strip(),
            reliability_note=reliability_note,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    # ------------------------------------------------------------------
    # KnowledgeState & ReviewItem
    # ------------------------------------------------------------------

    def update_knowledge_state(
        self,
        *,
        session_id: str,
        topic_id: str,
        target_status: KnowledgeMasteryStatus | str,
        reason: str,
        learner_id: str = "local_default_learner",
        unresolved_error_codes: list[str] | None = None,
        last_evidence_id: str | None = None,
        transfer_attempt_id: str | None = None,
    ) -> KnowledgeState:
        """Update or create KnowledgeState with mandatory traceability & transfer check guard."""
        target_enum = KnowledgeMasteryStatus(target_status)

        transfer_attempt: Attempt | None = None
        is_retried_transfer = False
        if transfer_attempt_id is not None:
            transfer_attempt = self.session.get(Attempt, transfer_attempt_id)
            if transfer_attempt is None:
                raise DomainRuleViolationError(
                    f"Unknown transfer_attempt_id: {transfer_attempt_id}"
                )
            if transfer_attempt.session_id != session_id or transfer_attempt.session.learner_id != learner_id:
                raise DomainRuleViolationError("Transfer evidence must belong to this learner and session.")
            # Check if this learner previously attempted the same transfer question and failed
            prior_failed_attempt_id = self.session.scalar(
                select(Attempt.id)
                .join(LearningSession, Attempt.session_id == LearningSession.id)
                .where(
                    LearningSession.learner_id == learner_id,
                    Attempt.question_id == transfer_attempt.question_id,
                    Attempt.id != transfer_attempt.id,
                    Attempt.is_correct.is_(False),
                )
            )
            if prior_failed_attempt_id is not None:
                is_retried_transfer = True
            if target_enum == KnowledgeMasteryStatus.STABLE:
                key = transfer_context_key(transfer_attempt.question.prompt_text, transfer_attempt.question.context_snippet)
                other_attempts = list(self.session.scalars(
                    select(Attempt).join(LearningSession, Attempt.session_id == LearningSession.id)
                    .where(LearningSession.learner_id == learner_id, LearningSession.topic_id == topic_id,
                           Attempt.id != transfer_attempt.id)
                ))
                if any(
                    prior.question_id == transfer_attempt.question_id
                    or transfer_context_key(prior.question_snapshot_json.get("prompt_text", prior.question.prompt_text),
                                            prior.question_snapshot_json.get("context_snippet", prior.question.context_snippet)) == key
                    for prior in other_attempts
                ):
                    is_retried_transfer = True
                if transfer_attempt.question.topic.domain_code in {"ielts_academic", "ielts_general_training"}:
                    material_key = self._attempt_material_fingerprint(transfer_attempt)
                    prior_materials = {self._attempt_material_fingerprint(prior) for prior in other_attempts}
                    prior_materials.update(self._assigned_reading_materials(learner_id, topic_id, exclude_session_id=session_id))
                    training_materials = {self._reading_material_fingerprint(q) for q in self.list_questions_for_topic(topic_id)
                                          if q.question_role in {QuestionRole.INITIAL.value, QuestionRole.DIAGNOSTIC_FOLLOWUP.value, QuestionRole.TARGETED_PRACTICE.value}}
                    if material_key is None or None in prior_materials or None in training_materials or material_key in prior_materials or material_key in training_materials:
                        is_retried_transfer = True
                if any(
                    question.question_role != QuestionRole.TRANSFER_CHECK.value
                    and transfer_context_key(question.prompt_text, question.context_snippet) == key
                    for question in self.list_questions_for_topic(topic_id)
                ):
                    is_retried_transfer = True

        existing = self.session.scalar(
            select(KnowledgeState).where(
                KnowledgeState.learner_id == learner_id,
                KnowledgeState.topic_id == topic_id,
            )
        )
        previous_state = existing.status if existing is not None else None

        # Pre-validate domain mastery rules before recording event
        validate_mastery_transition(
            target_enum,
            reason=reason,
            decision_event_id="pending_event_check",
            verified_transfer_attempt_role=(
                transfer_attempt.attempt_role if transfer_attempt else None
            ),
            verified_transfer_is_correct=(
                transfer_attempt.is_correct if transfer_attempt and transfer_attempt.evaluation_status == AttemptEvaluationStatus.EVALUATED.value else None
            ),
            verified_transfer_topic_matches=bool(
                transfer_attempt
                and self.session.get(Question, transfer_attempt.question_id) is not None
                and self.session.get(Question, transfer_attempt.question_id).topic_id  # type: ignore[union-attr]
                == topic_id
            ),
            is_retried_transfer_attempt=is_retried_transfer,
        )

        decision_event = self.append_decision_event(
            session_id=session_id,
            event_type="knowledge_state_updated",
            from_state=previous_state,
            to_state=target_enum.value,
            action="update_knowledge_state",
            reason=reason,
            uncertainty_level=(
                UncertaintyLevel.LOW
                if target_enum == KnowledgeMasteryStatus.STABLE
                else UncertaintyLevel.MEDIUM
            ),
            payload_json={
                "topic_id": topic_id,
                "transfer_attempt_id": transfer_attempt_id,
                "unresolved_error_codes": unresolved_error_codes or [],
            },
        )

        if existing is None:
            existing = KnowledgeState(
                learner_id=learner_id,
                topic_id=topic_id,
                status=target_enum.value,
                unresolved_error_codes=unresolved_error_codes or [],
                last_evidence_id=last_evidence_id,
                last_decision_event_id=decision_event.id,
                last_transfer_attempt_id=transfer_attempt_id,
                transition_reason=reason.strip(),
            )
            self.session.add(existing)
        else:
            existing.status = target_enum.value
            if unresolved_error_codes is not None:
                existing.unresolved_error_codes = unresolved_error_codes
            if last_evidence_id is not None:
                existing.last_evidence_id = last_evidence_id
            existing.last_decision_event_id = decision_event.id
            if transfer_attempt_id is not None:
                existing.last_transfer_attempt_id = transfer_attempt_id
            existing.transition_reason = reason.strip()

        self.session.flush()
        return existing

    def schedule_review_item(
        self,
        *,
        topic_id: str,
        trigger_reason: str,
        scheduled_for: datetime | None = None,
        learner_id: str = "local_default_learner",
        session_id: str | None = None,
        hypothesis_id: str | None = None,
        schedule_key: str | None = None,
        review_stage: int = 0,
    ) -> ReviewItem:
        if not trigger_reason or not trigger_reason.strip():
            raise DomainRuleViolationError("ReviewItem trigger_reason cannot be empty.")

        if schedule_key:
            existing = self.session.scalar(
                select(ReviewItem).where(ReviewItem.schedule_key == schedule_key)
            )
            if existing is not None:
                return existing
        review = ReviewItem(
            learner_id=learner_id,
            topic_id=topic_id,
            session_id=session_id,
            hypothesis_id=hypothesis_id,
            trigger_reason=trigger_reason.strip(),
            status=ReviewStatus.PENDING.value,
            scheduled_for=scheduled_for or utc_now(),
            schedule_key=schedule_key,
            review_stage=review_stage,
        )
        self.session.add(review)
        self.session.flush()
        return review

    # ------------------------------------------------------------------
    # ModelCall Audit & Diagnostic Budget Queries (Stage 3)
    # ------------------------------------------------------------------

    def record_model_call(
        self,
        *,
        provider_name: str,
        model_name: str,
        prompt_version: str,
        status: ModelCallStatus | str,
        redacted_summary: str,
        latency_ms: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        attempt_count: int = 1,
        error_code: str | None = None,
        session_id: str | None = None,
        diagnostic_case_id: str | None = None,
        decision_event_id: str | None = None,
    ) -> ModelCall:
        """Append a redacted ModelCall audit record."""
        status_enum = ModelCallStatus(status)
        call = ModelCall(
            session_id=session_id,
            diagnostic_case_id=diagnostic_case_id,
            decision_event_id=decision_event_id,
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
            status=status_enum.value,
            latency_ms=max(0, int(latency_ms)),
            prompt_tokens=max(0, int(prompt_tokens)),
            completion_tokens=max(0, int(completion_tokens)),
            total_tokens=max(0, int(total_tokens)),
            attempt_count=max(1, int(attempt_count)),
            error_code=error_code,
            redacted_summary=redacted_summary,
        )
        self.session.add(call)
        self.session.flush()
        return call

    def get_case_token_usage(self, diagnostic_case_id: str) -> int:
        """Sum total tokens consumed across all ModelCalls for a DiagnosticCase."""
        total = self.session.scalar(
            select(func.coalesce(func.sum(ModelCall.total_tokens), 0)).where(
                ModelCall.diagnostic_case_id == diagnostic_case_id
            )
        )
        return int(total or 0)

    def get_case_followup_turn_count(self, diagnostic_case_id: str) -> int:
        """Count how many diagnostic follow-up questions have been selected for this case."""
        count = self.session.scalar(
            select(func.count(DecisionEvent.id)).where(
                DecisionEvent.diagnostic_case_id == diagnostic_case_id,
                DecisionEvent.action == "select_diagnostic_followup",
            )
        )
        return int(count or 0)
