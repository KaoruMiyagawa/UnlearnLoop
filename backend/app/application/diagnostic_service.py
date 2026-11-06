"""Application service orchestrating Agent diagnostic workflows and decision steps."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    DiagnosticCaseResponse,
    DiagnosticStepResponse,
    EvidenceLinkResponse,
    HypothesisResponse,
)
from app.application.exceptions import EntityNotFoundError, InvalidSessionOperationError
from app.application.learning_service import LearningAppService
from app.config import Settings
from app.decision.agent_engine import DiagnosticAgentEngine
from app.domain.enums import (
    DiagnosticCaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    SessionStatus,
    UncertaintyLevel,
)
from app.model_provider import ModelProvider
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    LearningSession,
    Question,
)
from app.persistence.repositories import LearningRepository


class DiagnosticAppService:
    """Coordinates Agent diagnostic case inquiries, step executions, and retries."""

    def __init__(
        self,
        db_session: Session,
        model_provider: ModelProvider,
        settings: Settings,
    ) -> None:
        self.db = db_session
        self.repo = LearningRepository(db_session)
        self.model_provider = model_provider
        self.settings = settings

    def get_diagnostic_case(self, case_id: str) -> DiagnosticCaseResponse:
        """Fetch full diagnostic case view with current hypotheses and evidence count."""
        diag_case = self.repo.get_diagnostic_case(case_id)
        if diag_case is None:
            raise EntityNotFoundError("DiagnosticCase", case_id)

        evidence_links = self.repo.list_evidence_for_case(case_id)
        tokens_used = self.repo.get_case_token_usage(case_id)
        followup_turns = self.repo.get_case_followup_turn_count(case_id)

        hypotheses_dto = [
            HypothesisResponse(
                id=h.id,
                diagnostic_case_id=h.diagnostic_case_id,
                error_code=h.error_code,
                name=h.name,
                description=h.description,
                confidence=h.confidence,
                status=HypothesisStatus(h.status),
                missing_evidence_desc=h.missing_evidence_desc,
                created_at=h.created_at,
                updated_at=h.updated_at,
            )
            for h in diag_case.hypotheses
        ]

        latest_evt = (
            self.db.scalars(
                select(DecisionEvent)
                .where(DecisionEvent.diagnostic_case_id == diag_case.id)
                .order_by(DecisionEvent.created_at.desc())
            ).first()
        )
        unc_level = (
            UncertaintyLevel(latest_evt.uncertainty_level)
            if latest_evt and latest_evt.uncertainty_level
            else UncertaintyLevel.INSUFFICIENT_EVIDENCE
        )

        return DiagnosticCaseResponse(
            id=diag_case.id,
            session_id=diag_case.session_id,
            trigger_attempt_id=diag_case.trigger_attempt_id,
            status=DiagnosticCaseStatus(diag_case.status),
            uncertainty_level=unc_level,
            uncertainty_note=diag_case.uncertainty_note,
            followup_turn_count=followup_turns,
            tokens_used=tokens_used,
            hypotheses=hypotheses_dto,
            evidence_count=len(evidence_links),
            created_at=diag_case.created_at,
            updated_at=diag_case.updated_at,
        )

    def get_hypotheses_for_case(self, case_id: str) -> list[HypothesisResponse]:
        """List all candidate hypotheses attached to a diagnostic case."""
        case_resp = self.get_diagnostic_case(case_id)
        return case_resp.hypotheses

    def get_evidence_for_case(self, case_id: str) -> list[EvidenceLinkResponse]:
        """List all supporting and contradicting evidence links in a diagnostic case."""
        diag_case = self.repo.get_diagnostic_case(case_id)
        if diag_case is None:
            raise EntityNotFoundError("DiagnosticCase", case_id)

        links = self.repo.list_evidence_for_case(case_id)
        return [
            EvidenceLinkResponse(
                id=ev.id,
                hypothesis_id=ev.hypothesis_id,
                attempt_id=ev.attempt_id,
                source_type=EvidenceSourceType(ev.source_type),
                source_ref=ev.source_ref,
                relation=EvidenceRelation(ev.relation),
                summary=ev.summary,
                reliability_note=ev.reliability_note,
                created_at=ev.created_at,
            )
            for ev in links
        ]

    def run_step(
        self,
        case_id: str,
        idempotency_key: str | None = None,
    ) -> DiagnosticStepResponse:
        """Run a single controlled Agent diagnostic decision step."""
        diag_case = self.repo.get_diagnostic_case(case_id)
        if diag_case is None:
            raise EntityNotFoundError("DiagnosticCase", case_id)

        sess = self.repo.get_session(diag_case.session_id)
        if sess is None:
            raise EntityNotFoundError("LearningSession", diag_case.session_id)

        if sess.status == SessionStatus.PAUSED.value:
            raise InvalidSessionOperationError(
                "Cannot execute diagnostic step on a paused session; resume first.",
                current_state=sess.status,
            )

        # Release any uncommitted locks before model call
        self.db.commit()

        engine = DiagnosticAgentEngine(
            self.db,
            self.model_provider,
            settings=self.settings,
        )

        step_result = engine.run_diagnostic_step(
            session_id=sess.id,
            attempt_id=diag_case.trigger_attempt_id,
            diagnostic_case_id=diag_case.id,
            idempotency_key=idempotency_key,
        )
        self.db.commit()

        # If next question is selected, sanitize it
        next_q_dto = None
        if step_result.selected_question_id:
            q = self.repo.get_question_by_id(step_result.selected_question_id)
            if q is not None:
                next_q_dto = LearningAppService.sanitize_question(q)

        return DiagnosticStepResponse(
            session_id=step_result.session_id,
            diagnostic_case_id=step_result.diagnostic_case_id,
            case_status=step_result.case_status,
            executed_tool=step_result.executed_tool,
            selected_intervention=step_result.selected_intervention,
            selected_question_id=step_result.selected_question_id,
            next_question=next_q_dto,
            explanation_text=step_result.explanation_text,
            uncertainty_level=step_result.uncertainty_level,
            uncertainty_note=step_result.uncertainty_note,
            confidence_is_heuristic=step_result.confidence_is_heuristic,
            followup_turns_used=step_result.followup_turns_used,
            max_followup_turns=step_result.max_followup_turns,
            tokens_used_in_case=step_result.tokens_used_in_case,
            session_token_budget=step_result.session_token_budget,
            degraded_mode=step_result.degraded_mode,
            degradation_reason=step_result.degradation_reason,
            knowledge_state_status=step_result.knowledge_state_status,
            hypotheses=step_result.hypotheses_snapshot,
        )

    def retry_step(
        self,
        case_id: str,
        idempotency_key: str | None = None,
    ) -> DiagnosticStepResponse:
        """Retry a diagnostic step that entered RETRY_WAITING after a model failure."""
        diag_case = self.repo.get_diagnostic_case(case_id)
        if diag_case is None:
            raise EntityNotFoundError("DiagnosticCase", case_id)

        if diag_case.status == DiagnosticCaseStatus.RETRY_WAITING.value:
            # Re-transition to needs_evidence or collecting_attempt for clean retry
            self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.NEEDS_EVIDENCE,
                action="retry_diagnostic_step",
                reason="User or system triggered retry from retry_waiting state.",
            )
            self.db.commit()

        return self.run_step(case_id, idempotency_key=idempotency_key)
