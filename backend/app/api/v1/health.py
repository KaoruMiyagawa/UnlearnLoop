"""Health check endpoint and response models for /api/v1/health."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.config import Settings, get_settings

router = APIRouter(tags=["system"])


class SubsystemReadiness(BaseModel):
    """Readiness status for reserved architectural subsystems without leaking secrets."""

    persistence: Literal["configured", "unconfigured"] = Field(
        description="Whether SQLAlchemy database URL is configured."
    )
    model_provider: str = Field(
        description="Selected model provider identifier (e.g., deepseek, ollama)."
    )
    remote_model_enabled: bool = Field(
        description="Whether remote LLM calls are explicitly enabled and have a non-empty key."
    )


class HealthResponse(BaseModel):
    """Structured response schema for GET /api/v1/health."""

    status: Literal["ok"] = Field(default="ok", description="Service health status.")
    service: str = Field(description="Application name.")
    version: str = Field(description="Application version.")
    environment: Literal["development", "testing", "production"] = Field(
        description="Current runtime environment."
    )
    stage: str = Field(
        default="stage-1-foundation",
        description="Current roadmap implementation stage.",
    )
    timestamp: str = Field(description="Timezone-aware ISO 8601 server timestamp.")
    request_id: str = Field(description="Correlation request ID.")
    subsystems: SubsystemReadiness = Field(
        description="Readiness summary of persistence and model provider boundaries."
    )


@router.get("/health", response_model=HealthResponse, summary="Check backend health")
def get_health(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Return service health, version, request_id, and safe subsystem readiness."""
    request_id = getattr(request.state, "request_id", "req_unknown")
    persistence_state: Literal["configured", "unconfigured"] = (
        "configured" if bool(settings.database_url.strip()) else "unconfigured"
    )
    remote_ready = bool(
        settings.allow_remote_model_calls and settings.model_api_key.strip()
    )

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        stage="stage-1-foundation",
        timestamp=datetime.now(timezone.utc).isoformat(),
        request_id=request_id,
        subsystems=SubsystemReadiness(
            persistence=persistence_state,
            model_provider=settings.model_provider,
            remote_model_enabled=remote_ready,
        ),
    )
