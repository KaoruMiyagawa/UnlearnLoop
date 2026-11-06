"""Pytest fixtures for UnlearnLoop backend tests."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    """Return isolated test settings that do not depend on local .env secrets."""
    return Settings(
        APP_NAME="UnlearnLoop",
        APP_ENV="testing",
        APP_VERSION="0.1.0",
        DATABASE_URL="sqlite:///:memory:",
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
