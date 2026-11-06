"""Error taxonomy and secret redaction helpers for ModelProvider."""

import re

from app.domain.enums import ModelCallStatus

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{6,}", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)['\"]?[A-Za-z0-9_\-\.]{4,}['\"]?", re.IGNORECASE),
]


def redact_sensitive_text(text: str, max_length: int = 500) -> str:
    """Redact API keys, Bearer tokens, and secret assignments from any string."""
    cleaned = text
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED_SECRET]", cleaned)
    if len(cleaned) > max_length:
        return f"{cleaned[:max_length]}...[truncated]"
    return cleaned


class ModelProviderError(RuntimeError):
    """Base exception for all structured model provider failures."""

    status: ModelCallStatus = ModelCallStatus.PROVIDER_ERROR
    error_code: str = "MODEL_PROVIDER_ERROR"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        attempt_count: int = 1,
        latency_ms: int = 0,
    ) -> None:
        redacted_msg = redact_sensitive_text(message)
        super().__init__(redacted_msg)
        self.redacted_message = redacted_msg
        self.attempt_count = attempt_count
        self.latency_ms = latency_ms


class RemoteModelCallsDisabledError(ModelProviderError):
    """Raised when a remote API call is attempted while ALLOW_REMOTE_MODEL_CALLS=false or no key is set."""

    status = ModelCallStatus.REMOTE_DISABLED
    error_code = "REMOTE_MODEL_CALLS_DISABLED"
    retryable = False


class ModelTimeoutError(ModelProviderError):
    """Raised when a model provider request times out."""

    status = ModelCallStatus.TIMEOUT
    error_code = "MODEL_TIMEOUT"
    retryable = True


class ModelRateLimitError(ModelProviderError):
    """Raised when the model provider returns HTTP 429 rate limit / quota error."""

    status = ModelCallStatus.RATE_LIMITED
    error_code = "MODEL_RATE_LIMITED"
    retryable = True


class ModelServiceUnavailableError(ModelProviderError):
    """Raised when the model provider returns 5xx or transient network failure."""

    status = ModelCallStatus.SERVICE_UNAVAILABLE
    error_code = "MODEL_SERVICE_UNAVAILABLE"
    retryable = True


class ModelAuthenticationError(ModelProviderError):
    """Raised when the model provider returns HTTP 401/403 authentication failure."""

    status = ModelCallStatus.AUTH_ERROR
    error_code = "MODEL_AUTH_ERROR"
    retryable = False


class ModelInvalidJSONError(ModelProviderError):
    """Raised when the model response cannot be parsed as valid JSON."""

    status = ModelCallStatus.INVALID_JSON
    error_code = "MODEL_INVALID_JSON"
    retryable = False


class ModelSchemaValidationError(ModelProviderError):
    """Raised when parsed JSON violates the expected Pydantic schema."""

    status = ModelCallStatus.SCHEMA_ERROR
    error_code = "MODEL_SCHEMA_VALIDATION_ERROR"
    retryable = False


class ModelBudgetExceededError(ModelProviderError):
    """Raised when a call or diagnostic case exceeds its configured token budget."""

    status = ModelCallStatus.BUDGET_EXCEEDED
    error_code = "MODEL_TOKEN_BUDGET_EXCEEDED"
    retryable = False
