"""Pure domain rules and state transition matrices for UnlearnLoop."""

from app.domain.enums import (
    DiagnosticCaseStatus,
    HypothesisStatus,
    KnowledgeMasteryStatus,
    QuestionRole,
    SessionStatus,
)
from app.domain.exceptions import (
    DomainRuleViolationError,
    InvalidStateTransitionError,
    UnverifiedMasteryError,
)

# Controlled state transitions for LearningSession
ALLOWED_SESSION_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.ACTIVE: {
        SessionStatus.DIAGNOSING,
        SessionStatus.INTERVENING,
        SessionStatus.TRANSFER_CHECKING,
        SessionStatus.PAUSED,
    },
    SessionStatus.DIAGNOSING: {
        SessionStatus.DIAGNOSING,
        SessionStatus.INTERVENING,
        SessionStatus.TRANSFER_CHECKING,
        SessionStatus.PAUSED,
    },
    SessionStatus.INTERVENING: {
        SessionStatus.DIAGNOSING,
        SessionStatus.TRANSFER_CHECKING,
        SessionStatus.PAUSED,
    },
    SessionStatus.TRANSFER_CHECKING: {
        SessionStatus.DIAGNOSING,
        SessionStatus.INTERVENING,
        SessionStatus.COMPLETED,
        SessionStatus.PAUSED,
    },
    SessionStatus.PAUSED: {
        SessionStatus.ACTIVE,
        SessionStatus.DIAGNOSING,
        SessionStatus.INTERVENING,
        SessionStatus.TRANSFER_CHECKING,
    },
    SessionStatus.COMPLETED: set(),
}

# Controlled state transitions for DiagnosticCase (ARCHITECTURE.md Section 6)
ALLOWED_DIAGNOSTIC_CASE_TRANSITIONS: dict[
    DiagnosticCaseStatus, set[DiagnosticCaseStatus]
] = {
    DiagnosticCaseStatus.COLLECTING_ATTEMPT: {
        DiagnosticCaseStatus.INITIAL_EVALUATED,
        DiagnosticCaseStatus.RETRY_WAITING,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.INITIAL_EVALUATED: {
        DiagnosticCaseStatus.HYPOTHESES_GENERATED,
        DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.RETRY_WAITING,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.HYPOTHESES_GENERATED: {
        DiagnosticCaseStatus.NEEDS_EVIDENCE,
        DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
        DiagnosticCaseStatus.QUESTION_SELECTED,
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.NEEDS_EVIDENCE: {
        DiagnosticCaseStatus.QUESTION_SELECTED,
        DiagnosticCaseStatus.HYPOTHESES_UPDATED,
        DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.RETRY_WAITING,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE: {
        DiagnosticCaseStatus.QUESTION_SELECTED,
        DiagnosticCaseStatus.HYPOTHESES_UPDATED,
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.QUESTION_SELECTED: {
        DiagnosticCaseStatus.HYPOTHESES_UPDATED,
        DiagnosticCaseStatus.NEEDS_EVIDENCE,
        DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
        # A valid Agent proposal may choose an intervention without changing
        # hypothesis statuses (for example, the offline FakeModelProvider path).
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.RETRY_WAITING,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.HYPOTHESES_UPDATED: {
        DiagnosticCaseStatus.NEEDS_EVIDENCE,
        DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
        DiagnosticCaseStatus.QUESTION_SELECTED,
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.INTERVENTION_SELECTED: {
        DiagnosticCaseStatus.TRANSFER_CHECKING,
        DiagnosticCaseStatus.NEEDS_EVIDENCE,
        DiagnosticCaseStatus.RESOLVED,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.TRANSFER_CHECKING: {
        DiagnosticCaseStatus.TRANSFER_CHECKING,
        DiagnosticCaseStatus.RESOLVED,
        DiagnosticCaseStatus.HYPOTHESES_UPDATED,
        DiagnosticCaseStatus.NEEDS_EVIDENCE,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.RETRY_WAITING: {
        DiagnosticCaseStatus.NEEDS_EVIDENCE,
        DiagnosticCaseStatus.INITIAL_EVALUATED,
        DiagnosticCaseStatus.HYPOTHESES_GENERATED,
        DiagnosticCaseStatus.QUESTION_SELECTED,
        DiagnosticCaseStatus.HYPOTHESES_UPDATED,
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.PAUSED,
    },
    DiagnosticCaseStatus.PAUSED: {
        DiagnosticCaseStatus.COLLECTING_ATTEMPT,
        DiagnosticCaseStatus.INITIAL_EVALUATED,
        DiagnosticCaseStatus.NEEDS_EVIDENCE,
        DiagnosticCaseStatus.QUESTION_SELECTED,
        DiagnosticCaseStatus.INTERVENTION_SELECTED,
        DiagnosticCaseStatus.TRANSFER_CHECKING,
    },
    DiagnosticCaseStatus.RESOLVED: set(),
}

# Controlled state transitions for Hypothesis
ALLOWED_HYPOTHESIS_TRANSITIONS: dict[HypothesisStatus, set[HypothesisStatus]] = {
    HypothesisStatus.CANDIDATE: {
        HypothesisStatus.CANDIDATE,
        HypothesisStatus.INSUFFICIENT_EVIDENCE,
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.LOWERED,
        HypothesisStatus.RULED_OUT,
        HypothesisStatus.CONFIRMED,
    },
    HypothesisStatus.INSUFFICIENT_EVIDENCE: {
        HypothesisStatus.INSUFFICIENT_EVIDENCE,
        HypothesisStatus.CANDIDATE,
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.LOWERED,
        HypothesisStatus.RULED_OUT,
        HypothesisStatus.CONFIRMED,
    },
    HypothesisStatus.SUPPORTED: {
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.INSUFFICIENT_EVIDENCE,
        HypothesisStatus.LOWERED,
        HypothesisStatus.RULED_OUT,
        HypothesisStatus.CONFIRMED,
    },
    HypothesisStatus.LOWERED: {
        HypothesisStatus.LOWERED,
        HypothesisStatus.INSUFFICIENT_EVIDENCE,
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.RULED_OUT,
    },
    HypothesisStatus.CONFIRMED: {
        HypothesisStatus.CONFIRMED,
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.LOWERED,
    },
    HypothesisStatus.RULED_OUT: set(),
}


def validate_confidence(confidence: float) -> None:
    """Ensure hypothesis confidence stays within [0.0, 1.0]."""
    if not (0.0 <= confidence <= 1.0):
        raise DomainRuleViolationError(
            f"Hypothesis confidence must be between 0.0 and 1.0, got {confidence}."
        )


def validate_session_transition(
    current: SessionStatus | str,
    target: SessionStatus | str,
) -> None:
    """Validate that a LearningSession status transition is permitted."""
    current_enum = SessionStatus(current)
    target_enum = SessionStatus(target)
    if target_enum not in ALLOWED_SESSION_TRANSITIONS.get(current_enum, set()):
        raise InvalidStateTransitionError(
            f"Illegal LearningSession state transition: {current_enum} -> {target_enum}"
        )


def validate_diagnostic_case_transition(
    current: DiagnosticCaseStatus | str,
    target: DiagnosticCaseStatus | str,
    *,
    selected_question_answered: bool = False,
) -> None:
    """Validate that a DiagnosticCase status transition is permitted."""
    current_enum = DiagnosticCaseStatus(current)
    target_enum = DiagnosticCaseStatus(target)
    if (
        current_enum == DiagnosticCaseStatus.QUESTION_SELECTED
        and target_enum == DiagnosticCaseStatus.INTERVENTION_SELECTED
        and not selected_question_answered
    ):
        raise InvalidStateTransitionError(
            "Cannot select an intervention until the selected diagnostic question has been answered."
        )
    if target_enum not in ALLOWED_DIAGNOSTIC_CASE_TRANSITIONS.get(current_enum, set()):
        raise InvalidStateTransitionError(
            f"Illegal DiagnosticCase state transition: {current_enum} -> {target_enum}"
        )


def validate_hypothesis_transition(
    current: HypothesisStatus | str,
    target: HypothesisStatus | str,
) -> None:
    """Validate that a Hypothesis status transition is permitted."""
    current_enum = HypothesisStatus(current)
    target_enum = HypothesisStatus(target)
    if target_enum not in ALLOWED_HYPOTHESIS_TRANSITIONS.get(current_enum, set()):
        raise InvalidStateTransitionError(
            f"Illegal Hypothesis state transition: {current_enum} -> {target_enum}"
        )


def validate_mastery_transition(
    target_status: KnowledgeMasteryStatus | str,
    *,
    reason: str,
    decision_event_id: str | None,
    verified_transfer_attempt_role: QuestionRole | str | None = None,
    verified_transfer_is_correct: bool | None = None,
    verified_transfer_topic_matches: bool = False,
    is_retried_transfer_attempt: bool = False,
) -> None:
    """Enforce mastery transition traceability and transfer verification requirement.

    Domain rules:
    1. Every mastery state change must provide a non-empty reason and a DecisionEvent ID.
    2. A single correct answer on an initial/practice question CANNOT mark mastery as STABLE;
       transitioning to STABLE requires a passing transfer_check attempt on the same topic.
    3. If a learner previously failed a transfer question, retrying the same question (even if correct)
       CANNOT directly promote mastery to STABLE. An independent, unattempted transfer question is required.
    """
    target_enum = KnowledgeMasteryStatus(target_status)

    if not reason or not reason.strip():
        raise DomainRuleViolationError(
            "KnowledgeState transition requires a non-empty traceable reason."
        )

    if not decision_event_id or not decision_event_id.strip():
        raise DomainRuleViolationError(
            "KnowledgeState transition must reference a recorded DecisionEvent."
        )

    if target_enum == KnowledgeMasteryStatus.STABLE:
        if verified_transfer_attempt_role is None:
            raise UnverifiedMasteryError(
                "Cannot mark KnowledgeState as 'stable' without a verified transfer_check attempt."
            )
        role_enum = QuestionRole(verified_transfer_attempt_role)
        if role_enum != QuestionRole.TRANSFER_CHECK:
            raise UnverifiedMasteryError(
                f"Cannot mark KnowledgeState as 'stable' from a '{role_enum}' attempt; "
                "independent transfer verification ('transfer_check') is required."
            )
        if verified_transfer_is_correct is not True:
            raise UnverifiedMasteryError(
                "Cannot mark KnowledgeState as 'stable' when the transfer_check attempt is not correct."
            )
        if not verified_transfer_topic_matches:
            raise UnverifiedMasteryError(
                "Transfer verification attempt must belong to the same KnowledgeTopic."
            )
        if is_retried_transfer_attempt:
            raise UnverifiedMasteryError(
                "Cannot mark KnowledgeState as 'stable' using a retried transfer question that the learner previously failed; "
                "an independent, unattempted transfer verification question is required."
            )
