"""OpenAI-compatible, DeepSeek, and Ollama model provider adapters.

Implements ARCHITECTURE.md Section 7:
Request validation -> timeout control -> bounded retry (only on retryable errors)
-> JSON extraction & Pydantic schema validation -> redacted summary generation.
"""

import json
import re
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
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
from app.model_provider.schemas import ModelRequest, ModelResponse, TokenUsage

SchemaT = TypeVar("SchemaT", bound=BaseModel)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def parse_and_validate_json(
    raw_text: str,
    schema_cls: type[SchemaT],
    *,
    attempt_count: int = 1,
    latency_ms: int = 0,
) -> tuple[SchemaT, dict[str, Any]]:
    """Strip optional markdown code fences, parse JSON object, and validate against `schema_cls`."""
    cleaned = raw_text.strip()
    fence_match = _CODE_FENCE_RE.match(cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        parsed_json = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelInvalidJSONError(
            f"Model output is not valid JSON: {exc.msg}",
            attempt_count=attempt_count,
            latency_ms=latency_ms,
        ) from exc

    if not isinstance(parsed_json, dict):
        raise ModelInvalidJSONError(
            f"Expected a JSON object from model, got {type(parsed_json).__name__}.",
            attempt_count=attempt_count,
            latency_ms=latency_ms,
        )

    try:
        validated = schema_cls.model_validate(parsed_json)
    except ValidationError as exc:
        raise ModelSchemaValidationError(
            f"Model JSON failed schema validation for {schema_cls.__name__}: {exc.errors()}",
            attempt_count=attempt_count,
            latency_ms=latency_ms,
        ) from exc

    return validated, parsed_json


class OpenAICompatibleProvider:
    """Generic OpenAI-compatible chat completions adapter with timeout, retry, and schema validation."""

    def __init__(
        self,
        *,
        provider_name: str = "openai_compatible",
        model_name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        max_tokens_per_call: int | None = None,
        allow_remote_calls: bool | None = None,
        require_api_key: bool = True,
        http_client: httpx.Client | None = None,
        settings: Settings | None = None,
    ) -> None:
        resolved = settings or get_settings()
        self.provider_name = provider_name
        self.model_name = model_name or resolved.model_name
        self.base_url = (base_url or resolved.model_base_url).rstrip("/")
        self._api_key = api_key if api_key is not None else resolved.model_api_key
        self.timeout_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(resolved.model_timeout_seconds)
        )
        self.max_retries = (
            int(max_retries)
            if max_retries is not None
            else int(resolved.model_max_retries)
        )
        self.max_tokens_per_call = (
            int(max_tokens_per_call)
            if max_tokens_per_call is not None
            else int(resolved.model_max_tokens_per_call)
        )
        self.allow_remote_calls = (
            allow_remote_calls
            if allow_remote_calls is not None
            else resolved.allow_remote_model_calls
        )
        self.require_api_key = require_api_key
        self._http_client = http_client

    def is_configured(self) -> bool:
        """Return whether remote model calls are enabled and required credentials are set."""
        if not self.allow_remote_calls:
            return False
        if self.require_api_key and not self._api_key.strip():
            return False
        return bool(self.base_url and self.model_name)

    def _build_endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate_structured(
        self,
        request: ModelRequest,
        schema_cls: type[SchemaT],
    ) -> ModelResponse[SchemaT]:
        """Execute a schema-constrained chat completion call with bounded retries."""
        if not self.allow_remote_calls:
            raise RemoteModelCallsDisabledError(
                f"Provider '{self.provider_name}' blocked remote call because ALLOW_REMOTE_MODEL_CALLS is false."
            )
        if self.require_api_key and not self._api_key.strip():
            raise RemoteModelCallsDisabledError(
                f"Provider '{self.provider_name}' has no MODEL_API_KEY configured."
            )
        if request.max_tokens > self.max_tokens_per_call:
            raise ModelBudgetExceededError(
                f"Requested max_tokens ({request.max_tokens}) exceeds per-call limit ({self.max_tokens_per_call})."
            )

        endpoint = self._build_endpoint()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key.strip():
            headers["Authorization"] = f"Bearer {self._api_key.strip()}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": min(request.max_tokens, self.max_tokens_per_call),
            "response_format": {"type": "json_object"},
        }

        total_attempts = 0
        max_total_attempts = 1 + max(0, self.max_retries)
        start_time = time.perf_counter()
        last_error: ModelProviderError | None = None

        while total_attempts < max_total_attempts:
            total_attempts += 1
            try:
                if self._http_client is not None:
                    resp = self._http_client.post(
                        endpoint,
                        headers=headers,
                        json=payload,
                        timeout=self.timeout_seconds,
                    )
                else:
                    with httpx.Client(timeout=self.timeout_seconds) as client:
                        resp = client.post(endpoint, headers=headers, json=payload)

                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

                if resp.status_code in (401, 403):
                    raise ModelAuthenticationError(
                        f"Authentication failed with HTTP {resp.status_code} from {self.provider_name}.",
                        attempt_count=total_attempts,
                        latency_ms=elapsed_ms,
                    )
                if resp.status_code == 429:
                    raise ModelRateLimitError(
                        f"Rate limit exceeded (HTTP 429) from {self.provider_name}.",
                        attempt_count=total_attempts,
                        latency_ms=elapsed_ms,
                    )
                if resp.status_code >= 500:
                    raise ModelServiceUnavailableError(
                        f"Upstream server error (HTTP {resp.status_code}) from {self.provider_name}.",
                        attempt_count=total_attempts,
                        latency_ms=elapsed_ms,
                    )
                if resp.status_code >= 400:
                    raise ModelProviderError(
                        f"Unexpected HTTP {resp.status_code} from {self.provider_name}: {resp.text[:200]}",
                        attempt_count=total_attempts,
                        latency_ms=elapsed_ms,
                    )

                body = resp.json()
                choices = body.get("choices") or []
                if not choices or "message" not in choices[0]:
                    raise ModelInvalidJSONError(
                        "Response missing choices[0].message content.",
                        attempt_count=total_attempts,
                        latency_ms=elapsed_ms,
                    )
                content_text = str(choices[0]["message"].get("content", ""))
                validated, raw_json = parse_and_validate_json(
                    content_text,
                    schema_cls,
                    attempt_count=total_attempts,
                    latency_ms=elapsed_ms,
                )

                usage_raw = body.get("usage") or {}
                prompt_toks = int(usage_raw.get("prompt_tokens", 0))
                completion_toks = int(usage_raw.get("completion_tokens", 0))
                total_toks = int(
                    usage_raw.get("total_tokens", prompt_toks + completion_toks)
                )

                summary = redact_sensitive_text(
                    f"provider={self.provider_name} model={self.model_name} "
                    f"prompt_version={request.prompt_version} schema={schema_cls.__name__} "
                    f"tokens={total_toks} attempts={total_attempts}"
                )
                return ModelResponse(
                    parsed_output=validated,
                    raw_json=raw_json,
                    provider_name=self.provider_name,
                    model_name=self.model_name,
                    prompt_version=request.prompt_version,
                    latency_ms=elapsed_ms,
                    usage=TokenUsage(
                        prompt_tokens=prompt_toks,
                        completion_tokens=completion_toks,
                        total_tokens=total_toks,
                    ),
                    attempt_count=total_attempts,
                    redacted_summary=summary,
                )

            except httpx.TimeoutException as exc:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                last_error = ModelTimeoutError(
                    f"Request to {self.provider_name} timed out after {self.timeout_seconds}s: {exc}",
                    attempt_count=total_attempts,
                    latency_ms=elapsed_ms,
                )
            except httpx.RequestError as exc:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                last_error = ModelServiceUnavailableError(
                    f"Network error communicating with {self.provider_name}: {exc}",
                    attempt_count=total_attempts,
                    latency_ms=elapsed_ms,
                )
            except ModelProviderError as exc:
                last_error = exc
                if not exc.retryable:
                    raise

            if total_attempts >= max_total_attempts and last_error is not None:
                raise last_error

        assert last_error is not None
        raise last_error


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek API adapter built on the OpenAI-compatible protocol."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("provider_name", "deepseek")
        super().__init__(**kwargs)


class OllamaProvider(OpenAICompatibleProvider):
    """Local Ollama OpenAI-compatible adapter (does not require an API key)."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("provider_name", "ollama")
        kwargs.setdefault("base_url", "http://127.0.0.1:11434/v1")
        kwargs.setdefault("require_api_key", False)
        super().__init__(**kwargs)
