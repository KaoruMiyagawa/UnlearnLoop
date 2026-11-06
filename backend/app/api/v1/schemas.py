"""Pydantic request and response schemas for UnlearnLoop /api/v1 endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import (
    DiagnosticCaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    KnowledgeMasteryStatus,
    QuestionRole,
    QuestionType,
    SessionStatus,
    UncertaintyLevel,
)

# ---------------------------------------------------------------------------
# Common / Base Schemas
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error response payload."""

    code: str = Field(description="Stable error code.")
    message: str = Field(description="Human-readable error description.")
    request_id: str = Field(description="Correlation request identifier.")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Structured error details if any."
    )


# ---------------------------------------------------------------------------
# Topics & Materials & Questions
# ---------------------------------------------------------------------------


class TopicPrerequisiteSummary(BaseModel):
    """Prerequisite topic reference."""

    id: str
    slug: str
    title: str


class LearningMaterialResponse(BaseModel):
    """Learning material details."""

    id: str
    topic_id: str
    title: str
    summary: str
    content_body: str
    content_format: str
    version: int


class TopicSummaryResponse(BaseModel):
    """Summary of a knowledge topic for catalog display."""

    id: str
    slug: str
    domain_code: str
    title: str
    summary: str
    difficulty_level: int
    prerequisite_ids: list[str] = Field(default_factory=list)


class TopicDetailResponse(BaseModel):
    """Full detail of a knowledge topic, including prerequisites and materials."""

    id: str
    slug: str
    domain_code: str
    title: str
    summary: str
    difficulty_level: int
    prerequisites: list[TopicPrerequisiteSummary] = Field(default_factory=list)
    materials: list[LearningMaterialResponse] = Field(default_factory=list)
    common_error_patterns: list[dict[str, Any]] = Field(default_factory=list)
    questions_count: int


class SanitizedQuestionResponse(BaseModel):
    """Playable question payload sanitized for learner presentation.

    CRITICAL SECURITY CONTRACT:
    - Never exposes `standard_answer`.
    - Never exposes `answer_explanation`.
    - Never exposes `evaluation_rubric` (target error codes, expected outputs).
    """

    id: str
    topic_id: str
    material_id: str | None = None
    parent_question_id: str | None = None
    question_role: QuestionRole
    question_type: QuestionType
    prompt_text: str
    context_snippet: str | None = None
    difficulty: int
    version: int


# ---------------------------------------------------------------------------
# Learning Sessions
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    """Request payload to start a new learning session."""

    topic_id: str = Field(min_length=1, max_length=64, description="Target topic ID.")
    learner_id: str = Field(
        default="default_learner",
        min_length=1,
        max_length=64,
        description="Learner identifier (MVP single-user default).",
    )
    initial_question_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional specific initial question ID to start with.",
    )


class SessionActionRequest(BaseModel):
    """Request payload for session state actions (pause, resume, complete)."""

    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Reason for pausing, resuming, or completing the session.",
    )


class SessionSummaryResponse(BaseModel):
    """Summary of a learning session."""

    id: str
    topic_id: str
    topic_title: str
    learner_id: str
    status: SessionStatus
    current_question_id: str | None = None
    attempts_count: int = 0
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class SessionDetailResponse(BaseModel):
    """Detailed learning session state including current question and diagnostic pointer."""

    id: str
    topic_id: str
    topic_title: str
    learner_id: str
    status: SessionStatus
    current_question_id: str | None = None
    current_question: SanitizedQuestionResponse | None = None
    active_diagnostic_case_id: str | None = None
    attempts_count: int = 0
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Attempts (Answers)
# ---------------------------------------------------------------------------


class SubmitAttemptRequest(BaseModel):
    """Payload for submitting an answer to the current question."""

    question_id: str = Field(min_length=1, max_length=64, description="Question ID.")
    submitted_answer: str = Field(
        min_length=1,
        max_length=2000,
        description="Raw user-submitted answer or reasoning trace.",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="Optional client idempotency key to prevent duplicate submissions.",
    )


class AttemptSummaryResponse(BaseModel):
    """Summary of a historical attempt."""

    id: str
    session_id: str
    question_id: str
    question_role: str
    submitted_answer: str
    is_correct: bool | None = None
    evaluation_status: str
    evaluation_summary: str | None = None
    submitted_at: datetime


class AttemptDetailResponse(BaseModel):
    """Full detail of a recorded attempt."""

    id: str
    session_id: str
    question_id: str
    question_role: str
    question_version: int
    submitted_answer: str
    is_correct: bool | None = None
    evaluation_status: str
    evaluation_summary: str | None = None
    idempotency_key: str | None = None
    submitted_at: datetime


class AttemptResultResponse(BaseModel):
    """Response returned immediately upon submitting an attempt."""

    attempt_id: str
    session_id: str
    question_id: str
    question_role: str
    is_correct: bool | None = None
    evaluation_summary: str | None = None
    feedback_text: str | None = None
    next_action: str
    next_question: SanitizedQuestionResponse | None = None
    diagnostic_case_id: str | None = None
    knowledge_state_status: str | None = None


# ---------------------------------------------------------------------------
# Diagnoses & Hypotheses & Evidence
# ---------------------------------------------------------------------------


class HypothesisResponse(BaseModel):
    """Candidate error hypothesis view."""

    id: str
    diagnostic_case_id: str
    error_code: str
    name: str
    description: str | None = None
    confidence: float
    status: HypothesisStatus
    missing_evidence_desc: str | None = None
    created_at: datetime
    updated_at: datetime


class EvidenceLinkResponse(BaseModel):
    """Evidence linked to an error hypothesis."""

    id: str
    hypothesis_id: str
    attempt_id: str | None = None
    source_type: EvidenceSourceType
    source_ref: str
    relation: EvidenceRelation
    summary: str
    reliability_note: str | None = None
    created_at: datetime


class DiagnosticCaseResponse(BaseModel):
    """Diagnostic case state with candidate hypotheses and evidence summary."""

    id: str
    session_id: str
    trigger_attempt_id: str
    status: DiagnosticCaseStatus
    uncertainty_level: UncertaintyLevel
    uncertainty_note: str | None = None
    followup_turn_count: int
    tokens_used: int
    hypotheses: list[HypothesisResponse] = Field(default_factory=list)
    evidence_count: int = 0
    created_at: datetime
    updated_at: datetime


class DiagnosticStepRequest(BaseModel):
    """Request to trigger or step the Agent diagnosis engine."""

    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="Optional idempotency key for this diagnosis step.",
    )


class DiagnosticStepResponse(BaseModel):
    """Result of an Agent diagnostic decision step."""

    session_id: str
    diagnostic_case_id: str
    case_status: DiagnosticCaseStatus
    executed_tool: str
    selected_intervention: str | None = None
    selected_question_id: str | None = None
    next_question: SanitizedQuestionResponse | None = None
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
    knowledge_state_status: str | None = None
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Transfer Check & Interventions
# ---------------------------------------------------------------------------


class DispatchTransferRequest(BaseModel):
    """Request to assign or dispatch a transfer check."""

    force_fresh: bool = Field(
        default=True,
        description="Enforce selecting an independent fresh transfer question.",
    )


class TransferCheckDispatchResponse(BaseModel):
    """Result of dispatching a transfer check question."""

    question: SanitizedQuestionResponse | None = None
    session_status: SessionStatus
    degraded: bool = False
    message: str


# ---------------------------------------------------------------------------
# Reviews & Profile & Dashboard
# ---------------------------------------------------------------------------


class ReviewItemResponse(BaseModel):
    """Scheduled review item."""

    id: str
    topic_id: str
    topic_title: str
    session_id: str | None = None
    learner_id: str
    trigger_reason: str
    scheduled_for: datetime
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class CompleteReviewRequest(BaseModel):
    """Request payload to complete a scheduled review item."""

    review_notes: str | None = Field(
        default=None,
        max_length=500,
        description="Optional learner or tutor notes on the review completion.",
    )


class KnowledgeStateResponse(BaseModel):
    """Knowledge mastery state representation."""

    id: str
    learner_id: str
    topic_id: str
    topic_title: str
    topic_slug: str
    status: KnowledgeMasteryStatus
    confidence_is_heuristic: bool = True
    unresolved_error_codes: list[str] = Field(default_factory=list)
    transition_reason: str | None = None
    last_transfer_attempt_id: str | None = None
    updated_at: datetime


class DashboardSummaryResponse(BaseModel):
    """Learning dashboard summary for the learner."""

    learner_id: str
    total_sessions: int
    active_sessions: int
    completed_sessions: int
    total_attempts: int
    pending_reviews_count: int
    mastered_topics_count: int
    needs_practice_topics_count: int
    recent_sessions: list[SessionSummaryResponse] = Field(default_factory=list)
    pending_reviews: list[ReviewItemResponse] = Field(default_factory=list)
