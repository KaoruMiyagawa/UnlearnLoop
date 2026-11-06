"""Domain enumerations for UnlearnLoop (subject-agnostic)."""

from enum import StrEnum


class QuestionRole(StrEnum):
    """Pedagogical role of a question within the adaptive learning loop."""

    INITIAL = "initial"
    DIAGNOSTIC_FOLLOWUP = "diagnostic_followup"
    TARGETED_PRACTICE = "targeted_practice"
    TRANSFER_CHECK = "transfer_check"


class QuestionType(StrEnum):
    """Subject-agnostic question interaction format."""

    SHORT_TEXT = "short_text"
    CODE_TRACE = "code_trace"
    CODE_WRITING = "code_writing"
    MULTIPLE_CHOICE = "multiple_choice"


class SessionStatus(StrEnum):
    """Lifecycle states of a learning session."""

    ACTIVE = "active"
    DIAGNOSING = "diagnosing"
    INTERVENING = "intervening"
    TRANSFER_CHECKING = "transfer_checking"
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
    STABLE = "stable"


class ReviewStatus(StrEnum):
    """Lifecycle status of a scheduled review item."""

    PENDING = "pending"
    COMPLETED = "completed"
    REOPENED = "reopened"
