"""FastAPI dependencies for database sessions, model providers, and application services."""

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from app.application.diagnostic_service import DiagnosticAppService
from app.application.learning_service import LearningAppService
from app.config import Settings, get_settings
from app.model_provider import (
    DeepSeekProvider,
    FakeModelProvider,
    ModelProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
)
from app.persistence.database import create_session_factory

def get_session_factory(
    settings: Settings = Depends(get_settings),
) -> sessionmaker[Session]:
    return create_session_factory(create_db_engine(settings))


def get_db(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> Iterator[Session]:
    """Provide a database session per request with automatic commit and rollback."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_model_provider(
    settings: Settings = Depends(get_settings),
) -> ModelProvider:
    """Resolve the ModelProvider instance based on configuration."""
    if (
        settings.app_env == "testing"
        or settings.model_provider == "fake"
        or not settings.allow_remote_model_calls
        or not settings.model_api_key.strip()
    ):
        return FakeModelProvider()

    if settings.model_provider == "deepseek":
        return DeepSeekProvider(
            api_key=settings.model_api_key,
            base_url=settings.model_base_url,
            model=settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
        )

    if settings.model_provider == "ollama":
        return OllamaProvider(
            base_url=settings.model_base_url,
            model=settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
        )

    return OpenAICompatibleProvider(
        provider_name=settings.model_provider,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        model=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
    )


def get_learning_service(
    db: Session = Depends(get_db),
) -> LearningAppService:
    """Dependency injection for LearningAppService."""
    return LearningAppService(db)


def get_diagnostic_service(
    db: Session = Depends(get_db),
    provider: ModelProvider = Depends(get_model_provider),
    settings: Settings = Depends(get_settings),
) -> DiagnosticAppService:
    """Dependency injection for DiagnosticAppService."""
    return DiagnosticAppService(db, provider, settings)
