"""Domain enumerations for VerbaTrail (subject-agnostic)."""

from enum import StrEnum


class QuestionRole(StrEnum):
    """Pedagogical role of a question within the adaptive learning loop."""

    INITIAL = "initial"
    DIAGNOSTIC_FOLLOWUP = "diagnostic_followup"
    TARGETED_PRACTICE = "targeted_practice"
    TRANSFER_CHECK = "transfer_check"
    REVIEW = "review"


class QuestionType(StrEnum):
    """Subject-agnostic question interaction format."""

    SHORT_TEXT = "short_text"
    CODE_TRACE = "code_trace"
    CODE_WRITING = "code_writing"
    MULTIPLE_CHOICE = "multiple_choice"
    MATCHING_HEADINGS = "matching_headings"


class SessionStatus(StrEnum):
    """Lifecycle states of a learning session."""

    ACTIVE = "active"
    DIAGNOSING = "diagnosing"
    INTERVENING = "intervening"
    TRANSFER_CHECKING = "transfer_checking"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    PAUSED = "paused"


class AttemptEvaluationStatus(StrEnum):
    """Evaluation lifecycle status for a learner attempt."""

    PENDING = "pending"
    EVALUATED = "evaluated"
    RETRY_REQUIRED = "retry_required"


class DiagnosticCaseStatus(StrEnum):
    """State machine states for an error diagnosis case (ARCHITECTURE.md Section 6)."""

    COLLECTING_ATTEMPT = "collecting_attempt"
    INITIAL_EVALUATED = "initial_evaluated"
    HYPOTHESES_GENERATED = "hypotheses_generated"
    NEEDS_EVIDENCE = "needs_evidence"
    QUESTION_SELECTED = "question_selected"
    HYPOTHESES_UPDATED = "hypotheses_updated"
    INTERVENTION_SELECTED = "intervention_selected"
    TRANSFER_CHECKING = "transfer_checking"
    RESOLVED = "resolved"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RETRY_WAITING = "retry_waiting"
    PAUSED = "paused"


class HypothesisStatus(StrEnum):
    """Status of a candidate error hypothesis (PRD.md Section 4.2 & DESIGN_SYSTEM.md 3.4)."""

    CANDIDATE = "candidate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SUPPORTED = "supported"
    LOWERED = "lowered"
    RULED_OUT = "ruled_out"
    CONFIRMED = "confirmed"


class EvidenceSourceType(StrEnum):
    """Origin type of a piece of diagnostic evidence."""

    INITIAL_ATTEMPT = "initial_attempt"
    FOLLOWUP_RESPONSE = "followup_response"
    PRACTICE_ATTEMPT = "practice_attempt"
    TRANSFER_ATTEMPT = "transfer_attempt"
    RULE_CHECK = "rule_check"
    MODEL_EVALUATION = "model_evaluation"


class EvidenceRelation(StrEnum):
    """How a piece of evidence relates to a candidate hypothesis."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class InterventionAction(StrEnum):
    """Controlled set of pedagogical actions (PRD.md Section 3.1 & 5)."""

    ASK_FOLLOWUP = "ask_followup"
    EXPLAIN_CONCEPT = "explain_concept"
    TARGETED_PRACTICE = "targeted_practice"
    TRANSFER_CHECK = "transfer_check"
    SCHEDULE_REVIEW = "schedule_review"


class UncertaintyLevel(StrEnum):
    """Explicit uncertainty marker for diagnostic decisions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class KnowledgeMasteryStatus(StrEnum):
    """Interpretable knowledge mastery labels (DESIGN_SYSTEM.md Section 4.5)."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NEEDS_DIAGNOSIS = "needs_diagnosis"
    NEEDS_PRACTICE = "needs_practice"
    TRANSFER_VERIFIED = "transfer_verified"
    STABLE = "stable"


class ReviewStatus(StrEnum):
    """Lifecycle status of a scheduled review item."""

    PENDING = "pending"
    COMPLETED = "completed"
    REOPENED = "reopened"
    CANCELLED = "cancelled"


class EvidenceValidityStatus(StrEnum):
    """Current evidentiary fitness without rewriting the original assessment."""

    ELIGIBLE = "eligible"
    INVALIDATED = "invalidated"
    REVIEW_REQUIRED = "review_required"


class ModelCallStatus(StrEnum):
    """Execution outcome status of a ModelProvider call (ARCHITECTURE.md Section 4 & 7)."""

    SUCCEEDED = "succeeded"
    INVALID_JSON = "invalid_json"
    SCHEMA_ERROR = "schema_error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SERVICE_UNAVAILABLE = "service_unavailable"
    AUTH_ERROR = "auth_error"
    REMOTE_DISABLED = "remote_disabled"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROVIDER_ERROR = "provider_error"


class AgentToolName(StrEnum):
    """Whitelisted tool/action set available to the Diagnostic Agent (ARCHITECTURE.md Section 6)."""

    READ_MATERIAL_AND_QUESTION = "read_material_and_question"
    QUERY_ATTEMPTS_AND_EVIDENCE = "query_attempts_and_evidence"
    UPSERT_HYPOTHESES = "upsert_hypotheses"
    SELECT_DIAGNOSTIC_FOLLOWUP = "select_diagnostic_followup"
    PROVIDE_TARGETED_EXPLANATION = "provide_targeted_explanation"
    ASSIGN_TARGETED_PRACTICE = "assign_targeted_practice"
    ASSIGN_TRANSFER_VERIFICATION = "assign_transfer_verification"
    UPDATE_KNOWLEDGE_STATE = "update_knowledge_state"
