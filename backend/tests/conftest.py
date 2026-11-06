"""Pytest fixtures for UnlearnLoop backend tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.main import create_app
from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Return isolated test settings backed by a temporary SQLite file."""
    temp_db_file = tmp_path / "test_unlearnloop.db"
    return Settings(
        APP_NAME="UnlearnLoop",
        APP_ENV="testing",
        APP_VERSION="0.1.0",
        DATABASE_URL=f"sqlite:///{temp_db_file.as_posix()}",
        MODEL_PROVIDER="deepseek",
        MODEL_API_KEY="",
        ALLOW_REMOTE_MODEL_CALLS=False,
    )


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """Create a FastAPI TestClient bound to isolated test settings."""
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    return TestClient(app)


@pytest.fixture
def migrated_engine(test_settings: Settings) -> Iterator[Engine]:
    """Create an isolated temporary SQLite engine initialized via Alembic migrations."""
    engine = create_db_engine(test_settings)
    upgrade_database(database_url=test_settings.database_url, engine=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(migrated_engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to the migrated temporary test database."""
    return create_session_factory(migrated_engine)
