"""Model provider boundary (Stage 3 extension point).

Per ARCHITECTURE.md section 7:
- Business layers depend only on the ModelProvider protocol.
- Concrete adapters (DeepSeekProvider, OllamaProvider, FakeProvider) are implemented in Stage 3.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ModelProvider(Protocol):
    """Protocol interface reserved for structured AI model calls in Stage 3."""

    provider_name: str

    def is_configured(self) -> bool:
        """Return whether the provider has valid non-empty configuration."""
        ...

    def generate_structured(
        self,
        request: dict[str, Any],
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a schema-constrained model call (implemented in Stage 3)."""
        ...
