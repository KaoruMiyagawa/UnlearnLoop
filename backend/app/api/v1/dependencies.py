"""FastAPI dependencies for database sessions, model providers, and application services."""

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy import Engine
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
from app.persistence.database import create_db_engine, create_session_factory

_ENGINE_CACHE: dict[str, tuple[Engine, sessionmaker[Session]]] = {}


def get_or_create_engine_and_factory(
    settings: Settings,
) -> tuple[Engine, sessionmaker[Session]]:
    """Return a cached (Engine, sessionmaker) pair keyed by database_url to avoid per-request Engine creation."""
    cache_key = settings.database_url
    cached = _ENGINE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    _ENGINE_CACHE[cache_key] = (engine, factory)
    return engine, factory


def clear_engine_cache() -> None:
    """Dispose all cached SQLAlchemy engines and clear the cache."""
    for engine, _ in list(_ENGINE_CACHE.values()):
        engine.dispose()
    _ENGINE_CACHE.clear()


def get_session_factory(
    settings: Settings = Depends(get_settings),
) -> sessionmaker[Session]:
    """Provide the cached SQLAlchemy session factory for the configured database."""
    _, factory = get_or_create_engine_and_factory(settings)
    return factory


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
    """Resolve the ModelProvider instance based on configuration.

    Rules:
    - In testing mode, or when model_provider == 'fake', or when allow_remote_model_calls is False,
      return FakeModelProvider(allow_default_fallback=True) so offline / Demo mode is explicit.
    - When model_provider == 'ollama' and allow_remote_model_calls is True, do NOT require an API key.
    - For remote providers ('deepseek', 'openai_compatible'), fall back to FakeModelProvider
      if model_api_key is empty.
    """
    if (
        settings.app_env == "testing"
        or settings.model_provider == "fake"
        or not settings.allow_remote_model_calls
    ):
        return FakeModelProvider(allow_default_fallback=True)

    if settings.model_provider == "ollama":
        ollama_base_url = (
            "http://127.0.0.1:11434/v1"
            if settings.model_base_url.rstrip("/") == "https://api.deepseek.com"
            else settings.model_base_url
        )
        return OllamaProvider(
            base_url=ollama_base_url,
            model_name=settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
            max_tokens_per_call=settings.model_max_tokens_per_call,
            allow_remote_calls=settings.allow_remote_model_calls,
            settings=settings,
        )

    if not settings.model_api_key.strip():
        return FakeModelProvider(allow_default_fallback=True)

    if settings.model_provider == "deepseek":
        return DeepSeekProvider(
            api_key=settings.model_api_key,
            base_url=settings.model_base_url,
            model_name=settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
            max_tokens_per_call=settings.model_max_tokens_per_call,
            allow_remote_calls=settings.allow_remote_model_calls,
            settings=settings,
        )

    return OpenAICompatibleProvider(
        provider_name=settings.model_provider,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        model_name=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
        max_tokens_per_call=settings.model_max_tokens_per_call,
        allow_remote_calls=settings.allow_remote_model_calls,
        settings=settings,
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
