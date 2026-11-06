"""Tests for Stage 1 backend health check, request ID, and persistence hooks."""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.persistence.database import create_db_engine


def test_health_endpoint_returns_expected_contract(client: TestClient) -> None:
    """GET /api/v1/health returns 200 OK and adheres to the Stage 1 schema."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["service"] == "UnlearnLoop"
    assert data["version"] == "0.1.0"
    assert data["environment"] == "testing"
    assert data["stage"] == "stage-1-foundation"
    assert data["request_id"].startswith("req_")
    assert response.headers["X-Request-ID"] == data["request_id"]

    # Validate ISO 8601 timestamp with timezone
    parsed_time = datetime.fromisoformat(data["timestamp"])
    assert parsed_time.tzinfo is not None

    # Validate subsystem readiness contract without leaking secrets
    assert data["subsystems"] == {
        "persistence": "configured",
        "model_provider": "deepseek",
        "remote_model_enabled": False,
    }


def test_health_endpoint_preserves_caller_request_id(client: TestClient) -> None:
    """Custom X-Request-ID header is preserved in response header and payload."""
    custom_req_id = "req_custom_stage1_test"
    response = client.get("/api/v1/health", headers={"X-Request-ID": custom_req_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_req_id
    assert response.json()["request_id"] == custom_req_id


def test_settings_redact_api_key_in_repr() -> None:
    """Ensure model_api_key is never exposed when Settings is formatted or logged."""
    settings = Settings(MODEL_API_KEY="sk-test-placeholder-do-not-expose")
    assert "sk-test-placeholder-do-not-expose" not in repr(settings)


def test_sqlalchemy_engine_hook_executes_trivial_select(
    test_settings: Settings,
) -> None:
    """Verify the SQLAlchemy in-memory SQLite engine factory works cleanly."""
    engine = create_db_engine(test_settings)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar_one()
    assert result == 1
    engine.dispose()
