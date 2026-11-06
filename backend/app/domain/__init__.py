"""Domain layer boundary: enums, exceptions, and pure domain rules."""

from app.domain.enums import (
    AttemptEvaluationStatus,
    DiagnosticCaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    InterventionAction,
    KnowledgeMasteryStatus,
    QuestionRole,
    QuestionType,
    ReviewStatus,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.exceptions import (
    DomainRuleViolationError,
    ImmutableRecordError,
    InvalidStateTransitionError,
    UnverifiedMasteryError,
)
from app.domain.rules import (
    validate_confidence,
    validate_diagnostic_case_transition,
    validate_hypothesis_transition,
    validate_mastery_transition,
    validate_session_transition,
)

__all__ = [
    "AttemptEvaluationStatus",
    "DiagnosticCaseStatus",
    "DomainRuleViolationError",
    "EvidenceRelation",
    "EvidenceSourceType",
    "HypothesisStatus",
    "ImmutableRecordError",
    "InterventionAction",
    "InvalidStateTransitionError",
    "KnowledgeMasteryStatus",
    "QuestionRole",
    "QuestionType",
    "ReviewStatus",
    "SessionStatus",
    "UncertaintyLevel",
    "UnverifiedMasteryError",
    "validate_confidence",
    "validate_diagnostic_case_transition",
    "validate_hypothesis_transition",
    "validate_mastery_transition",
    "validate_session_transition",
]
