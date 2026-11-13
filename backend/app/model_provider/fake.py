"""Deterministic FakeModelProvider for offline Stage 3 testing and fixture replay."""

from collections import deque
from collections.abc import Callable
import json
from typing import Any, TypeVar

from pydantic import BaseModel

from app.model_provider.errors import (
    ModelBudgetExceededError,
    ModelProviderError,
    redact_sensitive_text,
)
from app.model_provider.openai_compatible import parse_and_validate_json
from app.model_provider.schemas import ModelRequest, ModelResponse, TokenUsage

SchemaT = TypeVar("SchemaT", bound=BaseModel)

ScriptedStep = (
    dict[str, Any]
    | str
    | BaseModel
    | Exception
    | tuple[dict[str, Any] | str | BaseModel, TokenUsage]
    | Callable[[ModelRequest], dict[str, Any] | str | BaseModel | Exception]
)


class FakeModelProvider:
    """Offline, scriptable ModelProvider supporting retries, invalid JSON, timeouts, and token simulation."""

    def __init__(
        self,
        scripted_steps: list[ScriptedStep] | None = None,
        *,
        provider_name: str = "fake",
        model_name: str = "fake-diagnostic-v1",
        max_retries: int = 2,
        max_tokens_per_call: int = 1024,
        default_token_usage: TokenUsage | None = None,
        allow_default_fallback: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.max_retries = max_retries
        self.max_tokens_per_call = max_tokens_per_call
        self.allow_default_fallback = allow_default_fallback
        self.default_token_usage = default_token_usage or TokenUsage(
            prompt_tokens=180,
            completion_tokens=120,
            total_tokens=300,
        )
        self._queue: deque[ScriptedStep] = deque(scripted_steps or [])
        self.recorded_requests: list[ModelRequest] = []

    def is_configured(self) -> bool:
        return True

    def enqueue(self, *steps: ScriptedStep) -> None:
        """Append one or more scripted responses or exceptions to the queue."""
        for step in steps:
            self._queue.append(step)

    @staticmethod
    def _build_default_demo_step(request: ModelRequest) -> dict[str, Any]:
        """Synthesize an explicit Demo/Mock decision proposal when running unscripted in dev mode."""
        followup_turns = 0
        try:
            payload = json.loads(request.user_prompt)
            followup_turns = int(
                payload.get("constraints", {}).get("followup_turns_used", 0)
            )
        except Exception:
            followup_turns = 0

        reading = request.metadata.get("domain_code") in {"ielts_academic", "ielts_general_training"}

        if followup_turns == 0:
            selected_tool = {
                "tool_name": "select_diagnostic_followup",
                "arguments": {
                    "discriminating_reason": (
                        "[DEMO/MOCK MODE] 离线模拟派发另一篇阅读题以收集更多证据；尚未验证该题能区分候选原因。"
                        if reading else "[DEMO/MOCK MODE] 模拟诊断追问：请补充每一步的中间计算状态以区分候选错误假设。"
                    )
                },
            }
        else:
            selected_tool = {
                "tool_name": "assign_targeted_practice",
                "arguments": {
                    "target_error_codes": [],
                    "practice_reason": ("[DEMO/MOCK MODE] 离线模拟派发阅读练习；不代表已实现个性化干预。" if reading else "[DEMO/MOCK MODE] 模拟针对性干预：分配针对性练习巩固核心概念。"),
                },
            }

        return {
            "reasoning": "[DEMO/MOCK MODE - FakeModelProvider] 当前未启用真实远程大模型，使用离线模拟决策流程。",
            "uncertainty_level": "insufficient_evidence",
            "uncertainty_note": "[DEMO/MOCK MODE] 当前处于离线模拟诊断模式（FakeModelProvider），非真实 AI 模型推理结果。",
            "hypothesis_updates": [],
            "selected_tool": selected_tool,
        }

    def generate_structured(
        self,
        request: ModelRequest,
        schema_cls: type[SchemaT],
    ) -> ModelResponse[SchemaT]:
        """Consume scripted steps with identical retry and schema validation rules as real providers."""
        self.recorded_requests.append(request)

        if request.max_tokens > self.max_tokens_per_call:
            raise ModelBudgetExceededError(
                f"Requested max_tokens ({request.max_tokens}) exceeds per-call limit ({self.max_tokens_per_call})."
            )

        total_attempts = 0
        max_total_attempts = 1 + max(0, self.max_retries)
        last_error: ModelProviderError | None = None

        while total_attempts < max_total_attempts:
            total_attempts += 1
            if not self._queue:
                if self.allow_default_fallback:
                    step: ScriptedStep = self._build_default_demo_step(request)
                else:
                    raise ModelProviderError(
                        "FakeModelProvider has no remaining scripted responses in queue.",
                        attempt_count=total_attempts,
                        latency_ms=5,
                    )
            else:
                step = self._queue.popleft()
            usage = self.default_token_usage

            if callable(step) and not isinstance(step, type):
                step = step(request)

            if isinstance(step, tuple) and len(step) == 2:
                step, usage = step

            if isinstance(step, Exception):
                if isinstance(step, ModelProviderError):
                    step.attempt_count = total_attempts
                    step.latency_ms = 5 * total_attempts
                    last_error = step
                    if not step.retryable:
                        raise step
                else:
                    raise ModelProviderError(
                        str(step),
                        attempt_count=total_attempts,
                        latency_ms=5 * total_attempts,
                    ) from step

                if total_attempts >= max_total_attempts:
                    raise last_error
                continue

            if isinstance(step, BaseModel):
                raw_text = step.model_dump_json()
            elif isinstance(step, dict):
                raw_text = json.dumps(step, ensure_ascii=False)
            else:
                raw_text = str(step)

            validated, raw_json = parse_and_validate_json(
                raw_text,
                schema_cls,
                attempt_count=total_attempts,
                latency_ms=5 * total_attempts,
            )
            summary = redact_sensitive_text(
                f"provider={self.provider_name} model={self.model_name} "
                f"prompt_version={request.prompt_version} schema={schema_cls.__name__} "
                f"tokens={usage.total_tokens} attempts={total_attempts}"
            )
            return ModelResponse(
                parsed_output=validated,
                raw_json=raw_json,
                provider_name=self.provider_name,
                model_name=self.model_name,
                prompt_version=request.prompt_version,
                latency_ms=5 * total_attempts,
                usage=usage,
                attempt_count=total_attempts,
                redacted_summary=summary,
            )

        assert last_error is not None
        raise last_error
