from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.dependencies import get_db, get_settings
from app.main import create_app
from app.persistence.models import Attempt, LearningSession


def test_listening_session_scores_persists_and_replays(session_factory: sessionmaker[Session], test_settings) -> None:
    app = create_app(test_settings)

    def isolated_db():
        with session_factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(app) as http:
        lesson = http.get("/api/v1/listening/lesson").json()
        assert len(lesson["questions"]) == 5
        assert "correct_answer" not in lesson["questions"][0]
        started = http.post("/api/v1/listening/sessions", json={"learner_id": "test-learner"})
        assert started.status_code == 201
        session = started.json()
        assert session["lesson"]["content_version"] == "listening-study-group-v1"
        answers = {q["id"]: ("Room 24" if q["number"] == 1 else q["options"][0]) for q in session["lesson"]["questions"]}
        payload = {"answers": answers, "idempotency_key": f"listen-{session['session_id']}"}
        submitted = http.post(f"/api/v1/listening/sessions/{session['session_id']}/submit", json=payload)
        assert submitted.status_code == 200
        result = submitted.json()
        assert result["score"] == 4
        assert result["results"][0]["question"]["start_seconds"] == 9.24
        assert "correct_answer" not in http.get("/api/v1/listening/lesson").json()["questions"][0]
        replay = http.post(f"/api/v1/listening/sessions/{session['session_id']}/submit", json=payload)
        assert replay.status_code == 200
        assert replay.json()["score"] == 4
        changed_answers = {**answers, "listening-study-group-v1-q1": "Room 12"}
        conflict = http.post(f"/api/v1/listening/sessions/{session['session_id']}/submit",
                             json={"answers": changed_answers, "idempotency_key": payload["idempotency_key"]})
        assert conflict.status_code == 409
        restored = http.get(f"/api/v1/listening/sessions/{session['session_id']}").json()
        assert restored["status"] == "completed"
        assert len(http.get("/api/v1/listening/history?learner_id=test-learner").json()) == 1

    with session_factory() as db:
        stored = db.scalars(select(Attempt).where(Attempt.session_id == session["session_id"])).all()
        saved_session = db.get(LearningSession, session["session_id"])
        assert len(stored) == 5
        assert all(row.evaluation_rule_version == "listening-exact-choice-v1" for row in stored)
        assert all(row.item_evaluation_json["evaluation_source"] == "rule_check" for row in stored)
        assert all(row.question_snapshot_json["content_version"] == "listening-study-group-v1" for row in stored)
        assert saved_session and saved_session.status == "completed"
