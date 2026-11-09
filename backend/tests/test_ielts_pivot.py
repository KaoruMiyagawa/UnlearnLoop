from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text

from app.api.v1.dependencies import get_session_factory
from app.config import Settings, get_settings
from app.main import create_app
from app.persistence.database import transactional_session
from app.persistence.seed import import_content_pack
from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database

IELTS_PACK = Path(__file__).parents[1] / "app" / "content" / "ielts_reading_pack.json"
ENGLISH_PACK = Path(__file__).parents[1] / "app" / "content" / "ielts_reading_english_pack.json"


@pytest.fixture
def ielts_client(session_factory: sessionmaker[Session], test_settings: Settings) -> Iterator[TestClient]:
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        import_content_pack(session, pack_path=IELTS_PACK)
        import_content_pack(session, pack_path=ENGLISH_PACK)
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with TestClient(app) as client:
        yield client


def test_exam_catalog_goals_persist_and_exams_are_isolated(ielts_client: TestClient) -> None:
    catalog = ielts_client.get("/api/v1/exams/catalog").json()
    assert len(catalog) == 7
    assert {item["code"] for item in catalog if item["availability"] == "available"} == {"academic", "general_training"}
    assert ielts_client.get("/api/v1/profile/exam-preparation").json()["target_overall_band"] == 8.0
    saved = ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "general_training", "target_overall_band": 8.5, "target_skill_bands": {"listening": 8, "reading": 8.5, "writing": 7.5, "speaking": 8}, "exam_date": "2027-08-20"})
    assert saved.status_code == 200
    assert saved.json()["exam_variant"] == "general_training"
    assert saved.json()["actual_level_status"] == "not_assessed"
    assert saved.json()["target_overall_band"] == 8.5
    assert saved.json()["target_skill_bands"]["writing"] == 7.5
    assert saved.json()["exam_date"] == "2027-08-20"
    assert ielts_client.get("/api/v1/profile/exam-preparation").json()["exam_variant"] == "general_training"
    assert ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "life_skills_a1"}).status_code == 400
    mismatch = ielts_client.post("/api/v1/sessions", json={"topic_id": "ielts-academic-reading"})
    assert mismatch.status_code == 400
    gt = ielts_client.post("/api/v1/sessions", json={"topic_id": "ielts-general-reading", "exam_variant": "general_training"})
    assert gt.status_code == 201
    assert gt.json()["exam_variant"] == "general_training"
    # Existing Python sessions stay outside the IELTS catalogue and snapshots.
    py = ielts_client.post("/api/v1/sessions", json={"topic_id": "topic_py_for_loop"})
    assert py.status_code == 201
    assert py.json()["exam_variant"] is None


def test_original_reading_answer_is_server_evaluated_and_diagnosis_is_real(ielts_client: TestClient) -> None:
    assert ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "academic"}).status_code == 200
    topics = ielts_client.get("/api/v1/topics?domain_code=ielts_academic").json()
    assert {topic["slug"] for topic in topics} >= {"ielts-academic-reading", "ielts-acad-reading-english"}
    session = ielts_client.post("/api/v1/sessions", json={"topic_id": "ielts-academic-reading", "exam_variant": "academic"}).json()
    question = session["current_question"]
    assert question["id"] == "ielts-acad-q-initial"
    assert "standard_answer" not in question and "evaluation_rubric" not in question
    wrong = ielts_client.post(f"/api/v1/sessions/{session['id']}/attempts", json={"question_id": question["id"], "submitted_answer": "A", "idempotency_key": "ielts-reading-wrong-1"})
    assert wrong.status_code == 201
    result = wrong.json()
    assert result["is_correct"] is False
    assert result["next_action"] == "diagnose"
    assert result["diagnostic_case_id"]
    case = ielts_client.get(f"/api/v1/diagnoses/{result['diagnostic_case_id']}")
    assert case.status_code == 200
    assert case.json()["is_mock_provider"] is True
    step = ielts_client.post(f"/api/v1/diagnoses/{result['diagnostic_case_id']}/step", json={"idempotency_key": "ielts-reading-diagnosis-1"})
    assert step.status_code == 200, step.text
    assert step.json()["next_question"]["question_role"] == "diagnostic_followup"
    assert step.json()["confidence_is_heuristic"] is True
    followup = step.json()["next_question"]
    followup_answer = ielts_client.post(f"/api/v1/sessions/{session['id']}/attempts", json={"question_id": followup["id"], "submitted_answer": "植物覆盖和降雨量都发生了变化", "idempotency_key": "ielts-reading-followup-1"})
    assert followup_answer.status_code == 201
    second_step = ielts_client.post(f"/api/v1/diagnoses/{result['diagnostic_case_id']}/step", json={"idempotency_key": "ielts-reading-diagnosis-2"})
    assert second_step.status_code == 200, second_step.text
    assert second_step.json()["next_question"]["question_role"] == "targeted_practice"
    practice = second_step.json()["next_question"]
    practiced = ielts_client.post(f"/api/v1/sessions/{session['id']}/attempts", json={"question_id": practice["id"], "submitted_answer": "B", "idempotency_key": "ielts-reading-practice-1"})
    assert practiced.status_code == 201
    assert practiced.json()["next_action"] == "transfer_check"
    transfer = practiced.json()["next_question"]
    assert transfer["question_role"] == "transfer_check"
    assert transfer["material_id"] == "ielts-acad-mat-3"
    verified = ielts_client.post(f"/api/v1/sessions/{session['id']}/attempts", json={"question_id": transfer["id"], "submitted_answer": "B", "idempotency_key": "ielts-reading-transfer-1"})
    assert verified.status_code == 201
    assert verified.json()["next_action"] == "mastery_achieved"
    assert verified.json()["knowledge_state_status"] == "stable"
    restored = ielts_client.get(f"/api/v1/sessions/{session['id']}").json()
    assert restored["exam_variant"] == "academic"
    assert restored["status"] == "transfer_checking"
    reviews = ielts_client.get("/api/v1/reviews?learner_id=default_learner&status=pending").json()
    assert any(item["topic_id"] == "ielts-academic-reading" for item in reviews)
    profile_states = ielts_client.get("/api/v1/profile/knowledge-states?learner_id=default_learner").json()
    assert any(state["topic_id"] == "ielts-academic-reading" and state["status"] == "stable" for state in profile_states)
    history = ielts_client.get("/api/v1/profile/history?learner_id=default_learner").json()
    assert any(event["topic_id"] == "ielts-academic-reading" for event in history)
    # A correct key is evaluated by the same IELTS evaluator, without Python trace heuristics.
    other = ielts_client.post("/api/v1/sessions", json={"topic_id": "ielts-academic-reading", "exam_variant": "academic"}).json()
    right = ielts_client.post(f"/api/v1/sessions/{other['id']}/attempts", json={"question_id": other["current_question_id"], "submitted_answer": "B", "idempotency_key": "ielts-reading-right-1"})
    assert right.status_code == 201
    assert right.json()["is_correct"] is True


def test_migration_0003_to_0004_keeps_python_session_without_exam_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "ielts-upgrade.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_db_engine(database_url=url)
    try:
        upgrade_database(database_url=url, engine=engine, revision="0003_evidence_based_reviews")
        factory = create_session_factory(engine)
        with transactional_session(factory) as db:
            import_content_pack(db)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO learning_sessions (id, learner_id, topic_id, current_question_id, status, started_at, updated_at) VALUES ('legacy-python-session', 'legacy-learner', 'topic_py_for_loop', 'q_py_loop_initial_01', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            connection.execute(text("INSERT INTO attempts (id, session_id, question_id, question_version, question_snapshot_json, attempt_role, submitted_answer, is_correct, evaluation_status, submitted_at) VALUES ('legacy-python-attempt', 'legacy-python-session', 'q_py_loop_initial_01', 1, '{}', 'initial', 'legacy answer', 0, 'evaluated', CURRENT_TIMESTAMP)"))
        upgrade_database(database_url=url, engine=engine)
        with factory() as db:
            from app.persistence.models import Attempt, LearningSession
            legacy = db.get(LearningSession, "legacy-python-session")
            assert legacy is not None
            assert legacy.exam_variant is None
            assert legacy.exam_spec_version is None
            assert legacy.topic.slug == "py-for-loop"
            attempt = db.get(Attempt, "legacy-python-attempt")
            assert attempt is not None and attempt.submitted_answer == "legacy answer"
    finally:
        engine.dispose()


def test_unknown_learning_domain_does_not_fall_back_to_python_rules() -> None:
    from app.domain.exceptions import DomainRuleViolationError
    from app.evaluation.registry import evaluator_for_domain
    with pytest.raises(DomainRuleViolationError, match="No objective evaluator"):
        evaluator_for_domain("future_unreviewed_domain")


def test_fake_reading_decision_explicitly_reports_its_limit() -> None:
    from app.model_provider.fake import FakeModelProvider
    from app.model_provider.schemas import ModelRequest
    request = ModelRequest(system_prompt="", user_prompt='{"constraints":{"followup_turns_used":0}}', metadata={"domain_code": "ielts_academic"})
    proposal = FakeModelProvider._build_default_demo_step(request)
    reason = proposal["selected_tool"]["arguments"]["discriminating_reason"]
    assert "尚未验证" in reason and "中间计算" not in reason


@pytest.mark.parametrize("variant,prefix,practice_key,transfer_key", [
    ("academic", "acad", "B", "B"),
    ("general_training", "gt", "A", "A"),
])
def test_english_reading_loop_keeps_exam_snapshot_after_switch(
    ielts_client: TestClient, session_factory: sessionmaker[Session],
    variant: str, prefix: str, practice_key: str, transfer_key: str,
) -> None:
    from sqlalchemy import select
    from app.persistence.models import Question, ReviewItem
    from app.persistence.repositories import LearningRepository

    saved = ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": variant, "exam_date": "2027-08-20"})
    assert saved.status_code == 200
    topic = f"ielts-{prefix}-reading-english"
    assert ielts_client.get(f"/api/v1/topics/{topic}").json()["materials"] == []
    assert ielts_client.get(f"/api/v1/topics/{topic}/materials").json() == []
    created = ielts_client.post("/api/v1/sessions", json={"topic_id": topic, "exam_variant": variant})
    assert created.status_code == 201, created.text
    current = created.json()
    assert current["exam_variant"] == variant
    assert current["current_question"]["material_id"] == f"ielts-{prefix}-english-mat-1"
    initial_material = ielts_client.get(f"/api/v1/sessions/{current['id']}/material").json()
    assert initial_material["id"] == f"ielts-{prefix}-english-mat-1"
    assert "##" not in initial_material["content_body"]
    other = "general_training" if variant == "academic" else "academic"
    assert ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": other, "exam_date": "2027-08-20"}).status_code == 200
    assert ielts_client.get(f"/api/v1/sessions/{current['id']}").json()["exam_variant"] == variant
    wrong = ielts_client.post(f"/api/v1/sessions/{current['id']}/attempts", json={"question_id": current["current_question_id"], "submitted_answer": "A", "idempotency_key": f"{prefix}-wrong"})
    assert wrong.status_code == 201 and wrong.json()["next_action"] == "diagnose"
    case_id = wrong.json()["diagnostic_case_id"]
    first = ielts_client.post(f"/api/v1/diagnoses/{case_id}/step", json={"idempotency_key": f"{prefix}-step-1"})
    assert first.status_code == 200, first.text
    assert first.json()["is_mock_provider"] is True
    evidence = ielts_client.get(f"/api/v1/diagnoses/{case_id}/evidence").json()
    assert any("作答“ A ”".replace(" ", "") in item["summary"] for item in evidence)
    follow = first.json()["next_question"]
    assert follow["material_id"] == f"ielts-{prefix}-english-mat-2"
    assert ielts_client.get(f"/api/v1/sessions/{current['id']}/material").json()["id"] == follow["material_id"]
    assert ielts_client.post(f"/api/v1/sessions/{current['id']}/attempts", json={"question_id": follow["id"], "submitted_answer": "A", "idempotency_key": f"{prefix}-follow"}).status_code == 201
    second = ielts_client.post(f"/api/v1/diagnoses/{case_id}/step", json={"idempotency_key": f"{prefix}-step-2"})
    assert second.status_code == 200, second.text
    practice = second.json()["next_question"]
    assert practice["material_id"] == f"ielts-{prefix}-english-mat-3"
    practiced = ielts_client.post(f"/api/v1/sessions/{current['id']}/attempts", json={"question_id": practice["id"], "submitted_answer": practice_key, "idempotency_key": f"{prefix}-practice"})
    assert practiced.status_code == 201 and practiced.json()["next_action"] == "transfer_check"
    transfer = practiced.json()["next_question"]
    assert transfer["material_id"] == f"ielts-{prefix}-english-mat-4"
    verified = ielts_client.post(f"/api/v1/sessions/{current['id']}/attempts", json={"question_id": transfer["id"], "submitted_answer": transfer_key, "idempotency_key": f"{prefix}-transfer"})
    assert verified.status_code == 201 and verified.json()["knowledge_state_status"] == "stable"
    assert ielts_client.get(f"/api/v1/sessions/{current['id']}").json()["exam_variant"] == variant
    with session_factory() as db:
        item = db.scalar(select(ReviewItem).where(ReviewItem.topic_id == topic))
        assert item is not None
        review_id = item.id
        repo = LearningRepository(db)
        review_question = repo.next_review_question(item)
        assert review_question is not None and review_question.material_id == f"ielts-{prefix}-english-mat-5"
        review_question.material_id = transfer["material_id"]
        db.flush()
        db.expire(review_question, ["material"])
        assert repo.next_review_question(item) is None
        review_question.material_id = f"ielts-{prefix}-english-mat-5"
        db.flush()
        db.expire(review_question, ["material"])
        transfer_question = db.get(Question, transfer["id"])
        assert transfer_question is not None and transfer_question.material is not None and review_question.material is not None
        review_question.material.content_body = transfer_question.material.content_body
        db.flush()
        assert repo.next_review_question(item) is None
    # An injected clock advances only this isolated service; the system clock and
    # development database remain untouched.
    from datetime import datetime, timedelta, timezone
    from app.application.learning_service import LearningAppService
    with session_factory() as db:
        service = LearningAppService(db, clock=lambda: datetime.now(timezone.utc) + timedelta(days=2))
        started = service.start_review(review_id, "default_learner")
        assert started.current_question is not None and started.review_session_id is not None
        reviewed = service.submit_attempt(started.review_session_id, started.current_question.id, "A", idempotency_key=f"{prefix}-review")
        assert reviewed.next_action == "delayed_retention_verified"


def test_ielts_targets_reject_out_of_range_or_non_half_bands(ielts_client: TestClient) -> None:
    assert ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "academic", "target_overall_band": 8.2}).status_code == 422
    assert ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "academic", "target_skill_bands": {"listening": 8, "reading": 9.5, "writing": 7, "speaking": 8}}).status_code == 422


@pytest.mark.parametrize("duplicate_by_content", [False, True])
def test_transfer_rejects_reused_reading_passage(ielts_client: TestClient, session_factory: sessionmaker[Session], duplicate_by_content: bool) -> None:
    from app.persistence.models import Question
    assert ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "academic"}).status_code == 200
    session = ielts_client.post("/api/v1/sessions", json={"topic_id": "ielts-acad-reading-english", "exam_variant": "academic"}).json()
    with session_factory() as db:
        initial = db.get(Question, "ielts-acad-english-initial")
        transfer = db.get(Question, "ielts-acad-english-transfer_check")
        assert initial is not None and transfer is not None and initial.material is not None and transfer.material is not None
        if duplicate_by_content:
            transfer.material.content_body = initial.material.content_body
        else:
            transfer.material_id = initial.material_id
        db.commit()
    result = ielts_client.post(f"/api/v1/sessions/{session['id']}/attempts", json={"question_id": session["current_question_id"], "submitted_answer": "B", "idempotency_key": f"duplicate-{duplicate_by_content}"})
    assert result.status_code == 201
    assert result.json()["next_action"] == "transfer_unavailable"
    assert result.json()["knowledge_state_status"] != "stable"


def test_unanswered_dispatched_transfer_cannot_be_reused_in_another_session(ielts_client: TestClient) -> None:
    assert ielts_client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "academic"}).status_code == 200
    def start_and_answer(key: str):
        session = ielts_client.post("/api/v1/sessions", json={"topic_id": "ielts-acad-reading-english", "exam_variant": "academic"}).json()
        result = ielts_client.post(f"/api/v1/sessions/{session['id']}/attempts", json={"question_id": session["current_question_id"], "submitted_answer": "B", "idempotency_key": key})
        assert result.status_code == 201
        return result.json()
    first = start_and_answer("seen-transfer-first")
    assert first["next_action"] == "transfer_check" and first["next_question"] is not None
    second = start_and_answer("seen-transfer-second")
    assert second["next_action"] == "transfer_unavailable"
    assert second["knowledge_state_status"] != "stable"
