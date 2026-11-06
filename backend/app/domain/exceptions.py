"""Domain exceptions enforcing business invariants and state transition rules."""


class DomainRuleViolationError(ValueError):
    """Raised when a domain invariant or immutability constraint is violated."""


class InvalidStateTransitionError(DomainRuleViolationError):
    """Raised when an entity attempts an illegal state machine transition."""


class UnverifiedMasteryError(DomainRuleViolationError):
    """Raised when attempting to mark knowledge as STABLE without transfer verification."""


class ImmutableRecordError(DomainRuleViolationError):
    """Raised when attempting to overwrite or delete append-only evidence/events/attempts."""
