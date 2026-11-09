from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.learning_service import LearningAppService
from app.api.v1.dependencies import get_session_factory
from app.config import Settings
from app.domain.enums import AttemptEvaluationStatus, KnowledgeMasteryStatus, QuestionRole
from app.persistence.models import Attempt, DecisionEvent, KnowledgeState, Question, ReviewItem
from app.persistence.repositories import LearningRepository
from app.persistence.database import create_db_engine, transactional_session
from app.persistence.migrations_runner import upgrade_database
from app.persistence.seed import import_content_pack
from app.main import create_app
from app.config import get_settings
import app.application.learning_service as learning_service_module


def make_seeded_client(session_factory: sessionmaker[Session], settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with transactional_session(session_factory) as db:
        import_content_pack(db)
    return TestClient(app)


def create_due_review(
    session_factory: sessionmaker[Session], learner_id: str, now: datetime,
) -> str:
    with transactional_session(session_factory) as db:
        import_content_pack(db)
        repo = LearningRepository(db)
        question = repo.get_question_by_id("q_py_loop_transfer_02")
        source = repo.create_session(
            topic_id=question.topic_id, learner_id=learner_id, current_question_id=question.id,
        )
        evidence = repo.record_attempt(
            session_id=source.id, question_id=question.id, submitted_answer="3 60",
            is_correct=True, evaluation_status=AttemptEvaluationStatus.EVALUATED,
            submitted_at=now - timedelta(minutes=1),
        )
        state = repo.update_knowledge_state(
            session_id=source.id, topic_id=source.topic_id,
            learner_id=learner_id, target_status=KnowledgeMasteryStatus.STABLE,
            reason="Test setup has a fresh independent transfer pass.",
            transfer_attempt_id=evidence.id,
        )
        assert state.status == KnowledgeMasteryStatus.STABLE.value
        service = LearningAppService(db, settings=Settings(), clock=lambda: now)
        item = service._schedule_review(
            learner_id=learner_id, topic_id=source.topic_id, session_id=source.id,
            trigger_attempt_id=evidence.id, reason="Test setup: delayed retention review.",
        )
        return item.id


def patch_clock(monkeypatch, value: list[datetime]) -> None:
    monkeypatch.setattr(learning_service_module, "utc_now", lambda: value[0])


def test_due_review_is_dispatched_answered_idempotently_and_rescheduled(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = [base]
    patch_clock(monkeypatch, clock)
    seeded_client = make_seeded_client(session_factory, test_settings)
    review_id = create_due_review(session_factory, "learner_review_a", base)

    listed = seeded_client.get("/api/v1/reviews?learner_id=learner_review_a").json()
    assert len(listed) == 1
    assert listed[0]["is_due"] is False
    early = seeded_client.post(f"/api/v1/reviews/{review_id}/start?learner_id=learner_review_a")
    assert early.status_code == 400

    clock[0] = base + timedelta(days=1, seconds=1)
    started = seeded_client.post(f"/api/v1/reviews/{review_id}/start?learner_id=learner_review_a")
    assert started.status_code == 200
    review = started.json()
    assert review["is_due"] is True
    assert review["current_question"]["question_role"] == QuestionRole.REVIEW.value
    assert "standard_answer" not in review["current_question"]
    resumed = seeded_client.post(f"/api/v1/reviews/{review_id}/start?learner_id=learner_review_a").json()
    assert resumed["review_session_id"] == review["review_session_id"]
    assert resumed["question_id"] == review["question_id"]
    fetched = seeded_client.get(f"/api/v1/reviews/{review_id}?learner_id=learner_review_a").json()
    assert fetched["question_id"] == review["question_id"]
    restarted_client = make_seeded_client(session_factory, test_settings)
    restored_after_restart = restarted_client.get(
        f"/api/v1/reviews/{review_id}?learner_id=learner_review_a",
    ).json()
    assert restored_after_restart["review_session_id"] == review["review_session_id"]
    assert restored_after_restart["question_id"] == review["question_id"]

    payload = {
        "question_id": review["question_id"], "submitted_answer": "3 12",
        "idempotency_key": "review-pass-once",
    }
    result = seeded_client.post(
        f"/api/v1/sessions/{review['review_session_id']}/attempts", json=payload,
    )
    assert result.status_code == 201, result.text
    assert result.json()["is_correct"] is True
    assert result.json()["next_action"] == "delayed_retention_verified"
    duplicate = seeded_client.post(
        f"/api/v1/sessions/{review['review_session_id']}/attempts", json=payload,
    )
    assert duplicate.status_code == 201
    assert duplicate.json() == result.json()

    completed = seeded_client.get(f"/api/v1/reviews/{review_id}?learner_id=learner_review_a").json()
    assert completed["status"] == "completed"
    assert completed["attempt_id"] == result.json()["attempt_id"]
    assert completed["retention_verified"] is True
    assert completed["knowledge_state_id"]
    assert completed["review_question"]["id"] == review["question_id"]
    assert completed["is_correct"] is True
    assert completed["submitted_at"]
    profile_state = seeded_client.get(
        "/api/v1/profile/knowledge-states?learner_id=learner_review_a",
    ).json()[0]
    assert profile_state["retention_status"] == "delayed_check_passed"
    assert profile_state["last_retention_verified_at"] == profile_state["last_reviewed_at"]
    next_review = seeded_client.get("/api/v1/reviews?learner_id=learner_review_a").json()
    assert len(next_review) == 1
    assert next_review[0]["review_stage"] == 1
    next_due = datetime.fromisoformat(next_review[0]["scheduled_for"].replace("Z", "+00:00"))
    assert next_due == clock[0] + timedelta(days=3)

    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt).where(
            Attempt.idempotency_key == "review-pass-once",
        )) == 1
        assert db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.action == "verify_delayed_retention",
        )) == 1


def test_failed_review_downgrades_current_status_and_creates_diagnosis(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
    monkeypatch,
) -> None:
    base = datetime(2026, 2, 1, tzinfo=timezone.utc)
    clock = [base]
    patch_clock(monkeypatch, clock)
    seeded_client = make_seeded_client(session_factory, test_settings)
    learner = "learner_review_failure"
    review_id = create_due_review(session_factory, learner, base)
    clock[0] += timedelta(days=1, seconds=1)
    review = seeded_client.post(f"/api/v1/reviews/{review_id}/start?learner_id={learner}").json()
    wrong = seeded_client.post(
        f"/api/v1/sessions/{review['review_session_id']}/attempts",
        json={"question_id": review["question_id"], "submitted_answer": "0", "idempotency_key": "review-fail-once"},
    )
    assert wrong.status_code == 201
    assert wrong.json()["is_correct"] is False
    assert wrong.json()["next_action"] == "review_failed_needs_diagnosis"
    assert wrong.json()["diagnostic_case_id"]
    state = seeded_client.get(f"/api/v1/profile/knowledge-states?learner_id={learner}").json()
    assert state[0]["status"] == KnowledgeMasteryStatus.NEEDS_PRACTICE.value
    assert state[0]["retention_status"] == "review_failed"
    assert state[0]["last_retention_verified_at"] is None

    details = seeded_client.get(f"/api/v1/reviews/{review_id}?learner_id={learner}").json()
    assert details["retention_verified"] is False
    assert details["review_outcome"] == "failed"
    assert details["attempt_id"] == wrong.json()["attempt_id"]
    pending = seeded_client.get(f"/api/v1/reviews?learner_id={learner}").json()
    assert len(pending) == 1
    assert pending[0]["retention_eligible"] is False
    scheduled = datetime.fromisoformat(pending[0]["scheduled_for"].replace("Z", "+00:00"))
    assert scheduled == clock[0] + timedelta(days=1)


def test_review_owner_legacy_completion_and_question_pool_exhaustion_are_safe(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
    monkeypatch,
) -> None:
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    clock = [base]
    patch_clock(monkeypatch, clock)
    seeded_client = make_seeded_client(session_factory, test_settings)
    learner = "learner_review_pool"
    review_id = create_due_review(session_factory, learner, base)
    clock[0] += timedelta(days=1, seconds=1)
    assert seeded_client.get(f"/api/v1/reviews/{review_id}?learner_id=someone_else").status_code == 404
    assert seeded_client.post(
        f"/api/v1/reviews/{review_id}/complete", json={"review_notes": "done"},
    ).status_code == 400

    with session_factory() as db:
        repo = LearningRepository(db)
        review_questions = db.scalars(select(Question).where(
            Question.topic_id == "topic_py_for_loop",
            Question.question_role == QuestionRole.REVIEW.value,
        )).all()
        for q in review_questions:
            prior = repo.create_session(
                topic_id=q.topic_id, learner_id=learner, current_question_id=q.id,
            )
            repo.record_attempt(
                session_id=prior.id, question_id=q.id, submitted_answer="previous",
                is_correct=False, evaluation_status=AttemptEvaluationStatus.EVALUATED,
            )
        db.commit()

    exhausted = seeded_client.post(f"/api/v1/reviews/{review_id}/start?learner_id={learner}")
    assert exhausted.status_code == 200
    assert exhausted.json()["current_question"] is None
    assert exhausted.json()["status"] == "pending"
    assert exhausted.json()["retention_verified"] is False


def test_review_schedule_duplicate_key_is_single_and_utc(
    session_factory: sessionmaker[Session],
) -> None:
    base = datetime(2026, 4, 1, 12, tzinfo=timezone(timedelta(hours=8)))
    utc = base.astimezone(timezone.utc)
    with transactional_session(session_factory) as db:
        import_content_pack(db)
        repo = LearningRepository(db)
        source = repo.create_session(topic_id="topic_py_for_loop", learner_id="learner_schedule")
        service = LearningAppService(db, settings=Settings(review_intervals_days=(1, 3, 7)), clock=lambda: base)
        first = service._schedule_review(
            learner_id=source.learner_id, topic_id=source.topic_id, session_id=source.id,
            trigger_attempt_id="attempt_schedule_key", reason="schedule once",
        )
        second = service._schedule_review(
            learner_id=source.learner_id, topic_id=source.topic_id, session_id=source.id,
            trigger_attempt_id="attempt_schedule_key", reason="schedule duplicate",
        )
        assert first.id == second.id
        assert first.scheduled_for.replace(tzinfo=timezone.utc) == utc + timedelta(days=1)
        assert db.scalar(select(func.count()).select_from(ReviewItem).where(
            ReviewItem.schedule_key == "retention:attempt_schedule_key:stage:0",
        )) == 1


def test_concurrent_review_start_returns_one_authoritative_session(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    patch_clock(monkeypatch, [base + timedelta(days=2)])
    client = make_seeded_client(session_factory, test_settings)
    learner = "learner_concurrent_review"
    review_id = create_due_review(session_factory, learner, base)

    def start():
        return client.post(f"/api/v1/reviews/{review_id}/start?learner_id={learner}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: start(), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["review_session_id"] == responses[1].json()["review_session_id"]
    assert responses[0].json()["question_id"] == responses[1].json()["question_id"]


def test_concurrent_review_answers_cannot_create_two_attempts_or_advance_twice(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    patch_clock(monkeypatch, [base + timedelta(days=2)])
    client = make_seeded_client(session_factory, test_settings)
    learner = "learner_concurrent_review_answer"
    review_id = create_due_review(session_factory, learner, base)
    review = client.post(f"/api/v1/reviews/{review_id}/start?learner_id={learner}").json()
    payload = {"question_id": review["question_id"], "submitted_answer": "3 12"}

    def submit():
        return client.post(f"/api/v1/sessions/{review['review_session_id']}/attempts", json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(), range(2)))

    successful = [response for response in responses if response.status_code == 201]
    assert len(successful) == 2, [response.text for response in responses]
    assert successful[0].json() == successful[1].json()
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt).where(
            Attempt.session_id == review["review_session_id"],
            Attempt.attempt_role == QuestionRole.REVIEW.value,
        )) == 1
        assert db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.session_id == review["review_session_id"],
            DecisionEvent.action == "verify_delayed_retention",
        )) == 1
        assert db.scalar(select(func.count()).select_from(ReviewItem).where(
            ReviewItem.learner_id == learner,
            ReviewItem.status == "pending",
        )) == 1


def test_profile_history_is_learner_scoped_and_never_returns_raw_answer_or_event_payload(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    client = make_seeded_client(session_factory, test_settings)
    learner = "learner_history_private"
    created = client.post("/api/v1/sessions", json={
        "topic_id": "topic_py_for_loop", "learner_id": learner,
    })
    assert created.status_code == 201, created.text
    session = created.json()
    answer_secret = "private learner answer must not appear in history"
    attempt = client.post(f"/api/v1/sessions/{session['id']}/attempts", json={
        "question_id": session["current_question_id"],
        "submitted_answer": answer_secret,
        "idempotency_key": "history-private-answer",
    })
    assert attempt.status_code == 201, attempt.text

    history = client.get(f"/api/v1/profile/history?learner_id={learner}")
    assert history.status_code == 200, history.text
    events = history.json()
    kinds = {event["kind"] for event in events}
    assert "incorrect_answer" in kinds
    assert "diagnosis" in kinds
    serialized = history.text
    assert answer_secret not in serialized
    assert "payload_json" not in serialized
    assert "standard_answer" not in serialized

    other_learner_history = client.get("/api/v1/profile/history?learner_id=another_learner")
    assert other_learner_history.status_code == 200
    assert other_learner_history.json() == []


def test_review_question_with_copied_context_under_new_id_is_excluded(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    patch_clock(monkeypatch, [base + timedelta(days=2)])
    client = make_seeded_client(session_factory, test_settings)
    learner = "learner_review_copy"
    review_id = create_due_review(session_factory, learner, base)
    with session_factory() as db:
        repo = LearningRepository(db)
        original = repo.get_question_by_id("q_py_loop_review_01")
        copied = Question(
            id="q_py_loop_review_01_copy", topic_id=original.topic_id,
            material_id=original.material_id, parent_question_id=original.parent_question_id,
            question_role=QuestionRole.REVIEW.value, question_type=original.question_type,
            prompt_text=original.prompt_text, context_snippet=original.context_snippet,
            standard_answer=original.standard_answer, answer_explanation=original.answer_explanation,
            evaluation_rubric=original.evaluation_rubric, difficulty=original.difficulty,
            version=original.version,
        )
        db.add(copied)
        prior = repo.create_session(
            topic_id=original.topic_id, learner_id=learner, current_question_id=original.id,
        )
        repo.record_attempt(
            session_id=prior.id, question_id=original.id, submitted_answer="3 12",
            is_correct=True, evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )
        db.commit()
    started = client.post(f"/api/v1/reviews/{review_id}/start?learner_id={learner}")
    assert started.status_code == 200
    assert started.json()["question_id"] == "q_py_loop_review_02"


def test_review_question_history_is_isolated_by_learner(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    patch_clock(monkeypatch, [base + timedelta(days=2)])
    client = make_seeded_client(session_factory, test_settings)
    review_id = create_due_review(session_factory, "learner_review_b", base)
    with session_factory() as db:
        repo = LearningRepository(db)
        question = repo.get_question_by_id("q_py_loop_review_01")
        previous = repo.create_session(
            topic_id=question.topic_id, learner_id="learner_review_a", current_question_id=question.id,
        )
        repo.record_attempt(
            session_id=previous.id, question_id=question.id, submitted_answer="3 12",
            is_correct=True, evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )
        db.commit()
    started = client.post(f"/api/v1/reviews/{review_id}/start?learner_id=learner_review_b")
    assert started.status_code == 200
    assert started.json()["question_id"] == "q_py_loop_review_01"


def test_migration_preserves_legacy_review_rows(
    test_settings: Settings,
) -> None:
    engine = create_db_engine(test_settings)
    try:
        upgrade_database(database_url=test_settings.database_url, engine=engine, revision="0002_stage3_model_calls")
        with engine.begin() as connection:
            connection.execute(text("""INSERT INTO knowledge_topics
                (id,slug,domain_code,title,summary,difficulty_level,common_error_patterns,created_at,updated_at)
                VALUES ('topic_legacy_review','legacy-review','python','Legacy review','compatibility',1,'[]',:now,:now)"""),
                {"now": "2026-01-01T00:00:00+00:00"})
            connection.execute(text("""INSERT INTO learning_sessions
                (id,learner_id,topic_id,current_question_id,status,started_at,updated_at,completed_at)
                VALUES ('session_legacy_review','legacy_learner','topic_legacy_review',NULL,'active',:now,:now,NULL)"""),
                {"now": "2026-01-01T00:00:00+00:00"})
            connection.execute(text("""INSERT INTO review_items
                (id,learner_id,topic_id,session_id,hypothesis_id,trigger_reason,status,scheduled_for,completed_at,review_outcome,created_at)
                VALUES ('review_legacy','legacy_learner','topic_legacy_review','session_legacy_review',NULL,
                'legacy schedule','pending',:now,NULL,NULL,:now)"""),
                {"now": "2026-01-01T00:00:00+00:00"})
        upgrade_database(database_url=test_settings.database_url, engine=engine)
        with Session(engine) as db:
            row = db.get(ReviewItem, "review_legacy")
            assert row is not None
            assert row.status == "pending"
            assert row.review_stage == 0
            assert row.retention_eligible is False
            assert row.attempt_id is None
            assert row.scheduled_for.replace(tzinfo=timezone.utc).isoformat() == "2026-01-01T00:00:00+00:00"
    finally:
        engine.dispose()
