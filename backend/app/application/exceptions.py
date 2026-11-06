"""Application-level exceptions and HTTP mapping helpers."""

from typing import Any


class ApplicationError(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "APPLICATION_ERROR",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class EntityNotFoundError(ApplicationError):
    """Raised when a requested resource does not exist."""

    def __init__(self, entity_name: str, entity_id: str) -> None:
        super().__init__(
            f"{entity_name} '{entity_id}' not found.",
            code="NOT_FOUND",
            status_code=404,
            details={"entity_name": entity_name, "entity_id": entity_id},
        )


class IdempotencyConflictError(ApplicationError):
    """Raised when an idempotency key conflicts with an existing conflicting operation."""

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(
            f"Idempotency key '{key}' conflict: {reason}",
            code="IDEMPOTENCY_CONFLICT",
            status_code=409,
            details={"idempotency_key": key, "reason": reason},
        )


class InvalidSessionOperationError(ApplicationError):
    """Raised when an operation is invalid for the session's current state."""

    def __init__(self, message: str, current_state: str | None = None) -> None:
        super().__init__(
            message,
            code="INVALID_SESSION_STATE",
            status_code=400,
            details={"current_state": current_state} if current_state else {},
        )
