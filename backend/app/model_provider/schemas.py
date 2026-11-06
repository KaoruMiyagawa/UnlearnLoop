"""Request and response schemas for structured ModelProvider calls."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class TokenUsage(BaseModel):
    """Token consumption metrics for a single model call."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ModelRequest(BaseModel):
    """Structured input for a schema-constrained model invocation."""

    prompt_version: str = Field(default="diag_agent_v1")
    system_prompt: str
    user_prompt: str
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    session_id: str | None = None
    diagnostic_case_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel, Generic[SchemaT]):
    """Validated structured response returned by a ModelProvider."""

    parsed_output: SchemaT
    raw_json: dict[str, Any]
    provider_name: str
    model_name: str
    prompt_version: str
    latency_ms: int = Field(default=0, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    attempt_count: int = Field(default=1, ge=1)
    redacted_summary: str
