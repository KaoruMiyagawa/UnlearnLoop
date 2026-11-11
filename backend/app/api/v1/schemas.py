"""Pydantic request and response schemas for VerbaTrail /api/v1 endpoints."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
from app.domain.reading_groups import HeadingResult

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
    """Full detail of a knowledge topic, including prerequisites and materials.

    SECURITY CONTRACT:
    - Never exposes internal `common_error_patterns` or diagnostic rubrics to learners;
      internal error patterns remain in the backend database for Agent diagnosis only.
    """

    id: str
    slug: str
    domain_code: str
    title: str
    summary: str
    difficulty_level: int
    prerequisites: list[TopicPrerequisiteSummary] = Field(default_factory=list)
    materials: list[LearningMaterialResponse] = Field(default_factory=list)
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
    group_version_id: str | None = None
    group_display: dict[str, Any] | None = None


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
    exam_variant: str | None = Field(default=None, max_length=32)
    question_type: QuestionType | None = None


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
    exam_variant: str | None = None
    exam_spec_version: str | None = None
    status: SessionStatus
    knowledge_state_status: KnowledgeMasteryStatus | None = None
    topic_mastered: bool = False
    current_question_id: str | None = None
    attempts_count: int = 0
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class SessionDetailResponse(BaseModel):
    """Detailed learning session state including current question, diagnostic pointer, and distinct mastery status."""

    id: str
    topic_id: str
    topic_title: str
    learner_id: str
    exam_variant: str | None = None
    exam_spec_version: str | None = None
    status: SessionStatus
    knowledge_state_status: KnowledgeMasteryStatus | None = None
    topic_mastered: bool = False
    current_question_id: str | None = None
    current_question: SanitizedQuestionResponse | None = None
    active_diagnostic_case_id: str | None = None
    latest_attempt_result: "AttemptResultResponse | None" = None
    can_dispatch_transfer: bool = False
    attempts_count: int = 0
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Attempts (Answers)
# ---------------------------------------------------------------------------


class SubmitAttemptRequest(BaseModel):
    """Payload for submitting an answer to the current question."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=64, description="Question ID.")
    group_version_id: str | None = Field(default=None, max_length=64)
    submitted_answer: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="Raw user-submitted answer or reasoning trace.",
    )
    structured_answer: dict[str, str] | None = Field(default=None, min_length=1, max_length=100)
    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="Optional client idempotency key to prevent duplicate submissions.",
    )

    @model_validator(mode="after")
    def exactly_one_answer(self):
        if (self.submitted_answer is None) == (self.structured_answer is None):
            raise ValueError("Provide exactly one of submitted_answer and structured_answer.")
        return self


class ReadingGroupEvaluation(HeadingResult):
    group_version_id: str
    content_version: str
    display_schema_version: str
    evaluation_rule_version: str
    rule_version_id: str
    evaluation_source: Literal["rule_check"] = "rule_check"


class AttemptSummaryResponse(BaseModel):
    """Summary of a historical attempt."""

    id: str
    session_id: str
    question_id: str
    question_role: str
    submitted_answer: str
    structured_answer: dict[str, str] | None = None
    group_evaluation: ReadingGroupEvaluation | None = None
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
    structured_answer: dict[str, str] | None = None
    group_evaluation: ReadingGroupEvaluation | None = None
    is_correct: bool | None = None
    evaluation_status: str
    evaluation_summary: str | None = None
    idempotency_key: str | None = None
    diagnostic_case_id: str | None = None
    evaluation_source: str | None = None
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
    evaluation_source: str = "rule_check"
    mastery_note: str | None = None
    group_evaluation: ReadingGroupEvaluation | None = None


SessionDetailResponse.model_rebuild()


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


class ReadingEvidenceSource(BaseModel):
    attempt_id: str
    item_id: str
    paragraph_id: str
    question_id: str
    group_version_id: str
    rule_version_id: str
    evaluation_rule_version: str
    diagnostic_protocol: str
    diagnostic_version: str
    selected_heading_id: str
    is_correct: bool


class EvidenceLinkResponse(BaseModel):
    """Evidence linked to an error hypothesis."""

    id: str
    hypothesis_id: str
    attempt_id: str | None = None
    source_type: EvidenceSourceType
    source_ref: str
    decision_event_id: str | None = None
    observation: ReadingEvidenceSource | None = None
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
    model_provider_name: str = "fake"
    is_mock_provider: bool = True
    execution_mode: str = "mock"
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
    decision_event_id: str | None = None
    decision_reason: str | None = None
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
    model_provider_name: str = "fake"
    is_mock_provider: bool = True
    execution_mode: str = "mock"
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
    review_stage: int = 0
    review_session_id: str | None = None
    question_id: str | None = None
    current_question: SanitizedQuestionResponse | None = None
    review_question: SanitizedQuestionResponse | None = None
    attempt_id: str | None = None
    is_correct: bool | None = None
    submitted_at: datetime | None = None
    evaluation_summary: str | None = None
    review_outcome: str | None = None
    retention_verified: bool = False
    retention_eligible: bool = False
    decision_event_id: str | None = None
    knowledge_state_id: str | None = None
    message: str | None = None
    is_due: bool = False


class CompleteReviewRequest(BaseModel):
    """Request payload to complete a scheduled review item."""

    review_notes: str | None = Field(
        default=None,
        max_length=500,
        description="Optional learner or tutor notes on the review completion.",
    )


class UnresolvedErrorReasonResponse(BaseModel):
    title: str
    summary: str
    status: str


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
    retention_status: str = "not_verified"
    retention_evidence_count: int = 0
    last_reviewed_at: datetime | None = None
    last_retention_verified_at: datetime | None = None
    unresolved_error_reasons: list[UnresolvedErrorReasonResponse] = Field(default_factory=list)


class ExamCatalogEntryResponse(BaseModel):
    code: str
    label: str
    base_variant: str | None
    scoring_system: Literal["band", "pass_fail"]
    availability: Literal["available", "planned"]
    purpose: str
    spec_version: str


class ExamPreparationProfileUpdate(BaseModel):
    exam_variant: str = Field(min_length=1, max_length=32)
    target_overall_band: float = Field(default=8.0, ge=1.0, le=9.0)
    target_skill_bands: dict[str, float] = Field(
        default_factory=lambda: {
            "listening": 8.0,
            "reading": 8.0,
            "writing": 8.0,
            "speaking": 8.0,
        }
    )
    exam_date: date | None = None

    @staticmethod
    def _check_band(value: float) -> float:
        if value < 1.0 or value > 9.0:
            raise ValueError("IELTS band targets must be between 1.0 and 9.0.")
        if round(value * 2) != value * 2:
            raise ValueError("IELTS band targets must use whole or half bands.")
        return value

    @field_validator("target_overall_band")
    @classmethod
    def validate_overall_band(cls, value: float) -> float:
        return cls._check_band(value)

    @field_validator("target_skill_bands")
    @classmethod
    def validate_skill_bands(cls, value: dict[str, float]) -> dict[str, float]:
        required = {"listening", "reading", "writing", "speaking"}
        if set(value) != required:
            raise ValueError("Skill targets must define Listening, Reading, Writing, and Speaking.")
        return {key: cls._check_band(band) for key, band in value.items()}


class ExamPreparationProfileResponse(BaseModel):
    learner_id: str
    selection_persisted: bool = True
    exam_variant: str
    selection_status: Literal["available", "planned"]
    goal_type: Literal["band", "pass"]
    target_overall_band: float | None = None
    target_skill_bands: dict[str, float] | None = None
    target_outcome: Literal["pass"] | None = None
    exam_date: date | None = None
    actual_level_status: Literal["not_assessed", "assessed"]
    current_skill_bands: dict[str, float | None]
    spec_version: str


class LearningHistoryEventResponse(BaseModel):
    id: str
    kind: str
    occurred_at: datetime
    topic_id: str
    topic_title: str
    title: str
    summary: str
    evidence_summary: str
    session_id: str | None = None
    attempt_id: str | None = None
    review_id: str | None = None


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
