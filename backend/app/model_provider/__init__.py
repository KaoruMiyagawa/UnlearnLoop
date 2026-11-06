"""Model provider protocol, concrete adapters, and structured error taxonomy."""

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.model_provider.errors import (
    ModelAuthenticationError,
    ModelBudgetExceededError,
    ModelInvalidJSONError,
    ModelProviderError,
    ModelRateLimitError,
    ModelSchemaValidationError,
    ModelServiceUnavailableError,
    ModelTimeoutError,
    RemoteModelCallsDisabledError,
    redact_sensitive_text,
)
from app.model_provider.fake import FakeModelProvider
from app.model_provider.openai_compatible import (
    DeepSeekProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    parse_and_validate_json,
)
from app.model_provider.schemas import ModelRequest, ModelResponse, TokenUsage

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@runtime_checkable
class ModelProvider(Protocol):
    """Protocol interface for schema-constrained AI model providers."""

    provider_name: str
    model_name: str

    def is_configured(self) -> bool:
        """Return whether the provider has valid non-empty configuration."""
        ...

    def generate_structured(
        self,
        request: ModelRequest,
        schema_cls: type[SchemaT],
    ) -> ModelResponse[SchemaT]:
        """Execute a schema-constrained model call and return validated `ModelResponse`."""
        ...


__all__ = [
    "DeepSeekProvider",
    "FakeModelProvider",
    "ModelAuthenticationError",
    "ModelBudgetExceededError",
    "ModelInvalidJSONError",
    "ModelProvider",
    "ModelProviderError",
    "ModelRateLimitError",
    "ModelRequest",
    "ModelResponse",
    "ModelSchemaValidationError",
    "ModelServiceUnavailableError",
    "ModelTimeoutError",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "RemoteModelCallsDisabledError",
    "TokenUsage",
    "parse_and_validate_json",
    "redact_sensitive_text",
]
