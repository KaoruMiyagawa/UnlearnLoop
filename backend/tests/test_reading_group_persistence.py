import copy

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.domain.exceptions import DomainRuleViolationError, ImmutableRecordError
from app.persistence.models import Attempt, LearningSession, Question, ReadingGroupVersion, ReadingRuleVersion
from app.persistence.reading_groups import import_matching_headings
from app.persistence.repositories import LearningRepository
from app.persistence.seed import import_content_pack


@pytest.fixture
def content():
    return {"id": "g1", "section_id": "s1", "display_schema_version": "1",
            "passage": {"id": "p1", "content_version": "1", "title": "Title",
                        "paragraphs": [{"id": "a", "text": "Paragraph one"}]},
            "options": [{"id": "i", "text": "First"}, {"id": "ii", "text": "Other"}],
            "items": [{"id": "item-a", "paragraph_id": "a"}]}


@pytest.fixture
def rules():
    return {"rules_version": "1", "answers": {"item-a": "i"}, "explanations": {"item-a": "reason"}}


def test_import_version_pinning_and_immutability(session_factory, content, rules):
    with session_factory() as db:
        import_content_pack(db)
        group = import_matching_headings(db, display=content, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"})
        assert import_matching_headings(db, display=content, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"}).id == group.id
        question = db.get(Question, "q_py_loop_initial_01")
        question.question_type = "matching_headings"
        question.reading_group_version_id = group.id
        db.flush()
        session = LearningRepository(db).create_session(topic_id=question.topic_id,
            current_question_id=question.id, exam_variant="academic")
        old_version = group.id
        assert session.current_group_version_id == old_version
        changed = copy.deepcopy(content)
        changed["passage"]["content_version"] = "2"
        changed["passage"]["paragraphs"][0]["text"] = "New passage"
        newer = import_matching_headings(db, display=changed, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"})
        assert newer.id != old_version and newer.rule_version_id == group.rule_version_id
        question.reading_group_version_id = newer.id
        db.commit()
        db.expire_all()
        assert db.get(type(session), session.id).current_group_version_id == old_version
        from app.application.learning_service import LearningAppService
        restored = LearningAppService(db).get_session_detail(session.id)
        assert restored.current_question.group_version_id == old_version
        assert restored.current_question.group_display["passage"]["paragraphs"][0]["text"] == "Paragraph one"
        # Re-dispatching the same question ID must pin its then-current version.
        session.current_question_id = question.id
        db.flush()
        assert session.current_group_version_id == newer.id
        review_session = LearningRepository(db).create_session(topic_id=question.topic_id,
            current_question_id=question.id, exam_variant="academic", status="reviewing")
        assert review_session.current_group_version_id == newer.id
        assert "answers" not in db.get(ReadingGroupVersion, old_version).display_json
        assert len(db.scalars(select(ReadingRuleVersion)).all()) == 1
        group = db.get(ReadingGroupVersion, old_version)
        group.content_version = "tampered"
        with pytest.raises(ImmutableRecordError):
            db.flush()


def test_public_schema_rejects_private_keys(session_factory, content, rules):
    content["answers"] = rules["answers"]
    with session_factory() as db, pytest.raises(ValueError):
        import_matching_headings(db, display=content, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"})


def test_snapshot_fields_and_version_mismatch(session_factory, content, rules):
    from app.application.learning_service import LearningAppService
    with session_factory() as db:
        import_content_pack(db)
        group = import_matching_headings(db, display=content, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"})
        question = db.get(Question, "q_py_loop_initial_01")
        question.question_type = "matching_headings"
        question.reading_group_version_id = group.id
        db.flush()
        session = LearningRepository(db).create_session(topic_id=question.topic_id,
            current_question_id=question.id, exam_variant="academic")
        attempt = Attempt(session_id=session.id, question_id=question.id, question_version=1,
            question_snapshot_json={}, attempt_role="initial", submitted_answer="legacy-compatible",
            group_version_id=group.id, structured_answer_json={"item-a": "ii"},
            group_snapshot_json=group.display_json, item_evaluation_json={"item-a": False},
            evaluation_rule_version="1", evaluation_status="evaluated")
        db.add(attempt)
        db.commit()
        db.expire_all()
        saved = db.get(Attempt, attempt.id)
        assert saved.structured_answer_json == {"item-a": "ii"}
        assert saved.item_evaluation_json == {"item-a": False}
        public = LearningAppService(db).get_session_detail(session.id).model_dump()
        assert public["current_question"]["group_version_id"] == group.id
        assert "private_rules_json" not in str(public)
        assert "item-a': 'i" not in str(public)
        with pytest.raises(DomainRuleViolationError, match="does not match"):
            LearningAppService(db).submit_attempt(session.id, question.id, "answer", group_version_id="other")
        saved.structured_answer_json = {"item-a": "i"}
        with pytest.raises(ImmutableRecordError):
            db.flush()


def test_assignment_rejects_other_exam_variant(session_factory, content, rules):
    with session_factory() as db:
        import_content_pack(db)
        group = import_matching_headings(db, display=content, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"})
        question = db.get(Question, "q_py_loop_initial_01")
        question.question_type = "matching_headings"
        question.reading_group_version_id = group.id
        db.flush()
        with pytest.raises(DomainRuleViolationError, match="exam variant"):
            LearningRepository(db).create_session(topic_id=question.topic_id,
                current_question_id=question.id, exam_variant="general_training")


def test_sqlite_rejects_bulk_updates_to_versions(session_factory, content, rules):
    with session_factory() as db:
        group = import_matching_headings(db, display=content, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"})
        db.commit()
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE reading_group_versions SET content_version='changed' WHERE id=:id"),
                       {"id": group.id})


def test_session_http_returns_pinned_public_content(session_factory, test_settings, content, rules):
    from pathlib import Path
    from fastapi.testclient import TestClient
    from app.api.v1.dependencies import get_session_factory
    from app.config import get_settings
    from app.main import create_app
    with session_factory() as db:
        import_content_pack(db, pack_path=Path(__file__).parents[1] / "app/content/ielts_reading_pack.json")
        version = import_matching_headings(db, display=content, private_rules=rules,
            exam_variant="academic", provenance={"source": "original", "license": "project"})
        question = db.get(Question, "ielts-acad-q-initial")
        question.reading_group_version_id = version.id
        question.question_type = "matching_headings"
        db.commit()
        version_id = version.id
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with TestClient(app) as client:
        assert client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "academic"}).status_code == 200
        created = client.post("/api/v1/sessions", json={"topic_id": "ielts-academic-reading", "exam_variant": "academic"})
        assert created.status_code == 201
        payload = created.json()
        assert payload["current_question"]["group_version_id"] == version_id
        assert '"answers"' not in created.text and '"private_rules_json"' not in created.text
        bad = client.post(f"/api/v1/sessions/{payload['id']}/attempts", json={
            "question_id": payload["current_question_id"], "group_version_id": "wrong", "submitted_answer": "i"})
        assert bad.status_code == 400
        correct_version = client.post(f"/api/v1/sessions/{payload['id']}/attempts", json={
            "question_id": payload["current_question_id"], "group_version_id": version_id, "submitted_answer": "i"})
        assert correct_version.status_code == 400


def test_upgrade_0004_preserves_historical_attempts(tmp_path):
    from tests.conftest import seed_historical_question
    from app.persistence.database import create_db_engine, create_session_factory
    from app.persistence.migrations_runner import upgrade_database
    url = f"sqlite:///{(tmp_path / 'historical.db').as_posix()}"
    engine = create_db_engine(database_url=url)
    try:
        upgrade_database(engine=engine, database_url=url, revision="0004_ielts_exam_profiles")
        for suffix in ("python", "tfng"):
            seed_historical_question(engine, "topic-" + suffix, "slug-" + suffix, "question-" + suffix)
            with engine.begin() as conn:
                if suffix == "tfng":
                    conn.execute(text("UPDATE knowledge_topics SET domain_code='ielts_academic' WHERE id='topic-tfng'"))
                    conn.execute(text("UPDATE questions SET evaluation_rubric=:rubric WHERE id='question-tfng'"),
                                 {"rubric": '{"diagnostic_protocol":"tfng-v1"}'})
                conn.execute(text("INSERT INTO learning_sessions (id,learner_id,topic_id,current_question_id,status,started_at,updated_at) VALUES (:id,'learner',:topic,:question,'active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),
                    {"id": "session-" + suffix, "topic": "topic-" + suffix, "question": "question-" + suffix})
                if suffix == "tfng":
                    conn.execute(text("UPDATE learning_sessions SET exam_variant='academic' WHERE id='session-tfng'"))
                conn.execute(text("INSERT INTO attempts (id,session_id,question_id,question_version,question_snapshot_json,attempt_role,submitted_answer,is_correct,evaluation_status,submitted_at) VALUES (:id,:session,:question,1,'{}','initial','original',0,'evaluated',CURRENT_TIMESTAMP)"),
                    {"id": "attempt-" + suffix, "session": "session-" + suffix, "question": "question-" + suffix})
        upgrade_database(engine=engine, database_url=url)
        with create_session_factory(engine)() as db:
            for suffix in ("python", "tfng"):
                assert db.get(Attempt, "attempt-" + suffix).submitted_answer == "original"
                assert db.get(LearningSession, "session-" + suffix).current_group_version_id is None
    finally:
        engine.dispose()
