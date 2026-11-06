"""Domain layer boundary: enums, exceptions, and pure domain rules."""

from app.domain.enums import (
    AgentToolName,
    AttemptEvaluationStatus,
    DiagnosticCaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    InterventionAction,
    KnowledgeMasteryStatus,
    ModelCallStatus,
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
    "AgentToolName",
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
    "ModelCallStatus",
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
