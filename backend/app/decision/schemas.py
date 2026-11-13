"""Pydantic schemas for Agent decision proposals, tool arguments, and step results."""

from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import (
    DiagnosticCaseStatus,
    EvidenceRelation,
    HypothesisStatus,
    KnowledgeMasteryStatus,
    UncertaintyLevel,
)


class HypothesisEvidenceProposal(BaseModel):
    """Evidence observation proposed by the Agent for a candidate hypothesis."""

    relation: EvidenceRelation
    summary: str = Field(min_length=1)


class HypothesisUpdateProposal(BaseModel):
    """Proposed creation or update of a candidate error hypothesis.

    Note: `heuristic_confidence` is a working judgment for ranking and uncertainty
    visibility, NOT a statistically calibrated probability.
    """

    error_code: str = Field(min_length=1)
    name: str | None = None
    description: str | None = None
    heuristic_confidence: float = Field(ge=0.0, le=1.0)
    status: HypothesisStatus
    missing_evidence_desc: str | None = None
    evidence_items: list[HypothesisEvidenceProposal] = Field(default_factory=list)


class AgentToolCallProposal(BaseModel):
    """Whitelisted tool invocation proposed by the Agent."""

    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentDecisionProposal(BaseModel):
    """Schema-constrained output required from ModelProvider during an Agent decision step."""

    reasoning: str = Field(min_length=1)
    uncertainty_level: UncertaintyLevel
    uncertainty_note: str | None = None
    confidence_is_heuristic: bool = Field(
        default=True,
        description="Explicit marker that confidence scores are heuristic working judgments.",
    )
    hypothesis_updates: list[HypothesisUpdateProposal] = Field(default_factory=list)
    selected_tool: AgentToolCallProposal


# ---------------------------------------------------------------------------
# Whitelisted Tool Argument Schemas
# ---------------------------------------------------------------------------


class SelectFollowupArgs(BaseModel):
    """Validated arguments for `select_diagnostic_followup`."""

    followup_question_id: str | None = None
    target_error_codes: list[str] = Field(default_factory=list)
    discriminating_reason: str = Field(min_length=1)


class ProvideExplanationArgs(BaseModel):
    """Validated arguments for `provide_targeted_explanation`."""

    target_error_codes: list[str] = Field(default_factory=list)
    explanation_text: str = Field(min_length=1)
    schedule_review: bool = False


class AssignPracticeArgs(BaseModel):
    """Validated arguments for `assign_targeted_practice`."""

    practice_question_id: str | None = None
    target_error_codes: list[str] = Field(default_factory=list)
    practice_reason: str = Field(min_length=1)


class AssignTransferArgs(BaseModel):
    """Validated arguments for `assign_transfer_verification`."""

    transfer_question_id: str | None = None
    transfer_reason: str = Field(min_length=1)


class UpdateKnowledgeStateArgs(BaseModel):
    """Validated arguments for `update_knowledge_state`."""

    target_status: KnowledgeMasteryStatus
    reason: str = Field(min_length=1)
    unresolved_error_codes: list[str] = Field(default_factory=list)
    transfer_attempt_id: str | None = None
    schedule_review: bool = False
    review_reason: str | None = None


class DiagnosticStepResult(BaseModel):
    """Structured result returned after executing one step of the Diagnostic Agent."""

    session_id: str
    diagnostic_case_id: str
    attempt_id: str
    case_status: DiagnosticCaseStatus
    executed_tool: str
    selected_intervention: str | None = None
    selected_question_id: str | None = None
    selected_group_version_id: str | None = None
    explanation_text: str | None = None
    uncertainty_level: UncertaintyLevel
    uncertainty_note: str | None = None
    confidence_is_heuristic: bool = True
    followup_turns_used: int
    max_followup_turns: int
    tokens_used_in_case: int
    session_token_budget: int
    degraded_mode: bool = False
    degradation_reason: str | None = None
    decision_event_id: str
    hypotheses_snapshot: list[dict[str, Any]]
    knowledge_state_status: str | None = None
