"""Application configuration loaded from environment variables or .env files."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Centralized backend settings with safe defaults for local development."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="UnlearnLoop", validation_alias="APP_NAME")
    app_env: Literal["development", "testing", "production"] = Field(
        default="development",
        validation_alias="APP_ENV",
    )
    app_version: str = Field(default="0.1.0", validation_alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    backend_host: str = Field(default="127.0.0.1", validation_alias="BACKEND_HOST")
    backend_port: int = Field(default=18000, validation_alias="BACKEND_PORT")
    cors_origins: str = Field(
        default="http://localhost:15173,http://127.0.0.1:15173,http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="CORS_ORIGINS",
    )

    # Persistence hook (SQLite + SQLAlchemy reserved for Stage 2)
    database_url: str = Field(
        default="sqlite:///./unlearnloop.db",
        validation_alias="DATABASE_URL",
    )

    # Model provider hook (DeepSeek / Ollama reserved for Stage 3)
    model_provider: str = Field(default="deepseek", validation_alias="MODEL_PROVIDER")
    model_name: str = Field(default="deepseek-chat", validation_alias="MODEL_NAME")
    model_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias="MODEL_BASE_URL",
    )
    model_api_key: str = Field(default="", validation_alias="MODEL_API_KEY", repr=False)
    model_timeout_seconds: int = Field(
        default=30,
        validation_alias="MODEL_TIMEOUT_SECONDS",
    )
    model_max_retries: int = Field(default=2, validation_alias="MODEL_MAX_RETRIES")
    model_max_tokens_per_call: int = Field(
        default=1024,
        validation_alias="MODEL_MAX_TOKENS_PER_CALL",
    )
    model_temperature: float = Field(
        default=0.1,
        validation_alias="MODEL_TEMPERATURE",
    )
    allow_remote_model_calls: bool = Field(
        default=False,
        validation_alias="ALLOW_REMOTE_MODEL_CALLS",
    )

    # Stage 3 Agent loop & budget limits
    max_diagnostic_followup_turns: int = Field(
        default=2,
        validation_alias="MAX_DIAGNOSTIC_FOLLOWUP_TURNS",
    )
    diagnostic_session_token_budget: int = Field(
        default=4096,
        validation_alias="DIAGNOSTIC_SESSION_TOKEN_BUDGET",
    )

    # JSON array in the environment, e.g. REVIEW_INTERVALS_DAYS='[1,3,7,14,30]'.
    review_intervals_days: tuple[int, ...] = Field(
        default=(1, 3, 7, 14, 30), validation_alias="REVIEW_INTERVALS_DAYS"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a clean list."""
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
