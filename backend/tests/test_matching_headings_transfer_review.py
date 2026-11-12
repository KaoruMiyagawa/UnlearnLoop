"""Matching Headings transfer and delayed review use the existing learning records."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.dependencies import get_db
from app.application.learning_service import LearningAppService
from app.config import Settings, get_settings
from app.domain.enums import KnowledgeMasteryStatus, QuestionRole, ReviewStatus
from app.persistence.models import (
    Attempt, DiagnosticCase, EvidenceLink, KnowledgeState, LearningSession,
    Question, ReadingGroupVersion, ReadingRuleVersion, ReviewItem,
)
from app.persistence.reading_groups import import_matching_headings
from app.persistence.database import create_db_engine
from app.persistence.migrations_runner import upgrade_database
from app.persistence.seed import import_content_pack, load_matching_headings_diagnostic_pack
from tests.test_ielts_pivot import ielts_client  # noqa: F401


@pytest.fixture
def phase4_client(ielts_client, session_factory, test_settings):
    with session_factory.begin() as db:
        import_content_pack(db, pack_data=load_matching_headings_diagnostic_pack(db))
    now = [datetime(2026, 4, 1, 12, tzinfo=timezone.utc)]

    def learning_service(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
        return LearningAppService(db, settings=settings, clock=lambda: now[0])

    ielts_client.app.dependency_overrides[
        __import__("app.api.v1.dependencies", fromlist=["get_learning_service"]).get_learning_service
    ] = learning_service
    return ielts_client, session_factory, now


def _answer_for(factory, question):
    with factory() as db:
        group = db.get(ReadingGroupVersion, question["group_version_id"])
        key = db.get(ReadingRuleVersion, group.rule_version_id)
        return dict(key.private_rules_json["answers"])


def _submit(client, session_id, question, answer, key):
    response = client.post(f"/api/v1/sessions/{session_id}/attempts", json={
        "question_id": question["id"], "group_version_id": question["group_version_id"],
        "structured_answer": answer, "idempotency_key": key,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _reach_transfer(client, factory, variant, target, prefix, *, dispatch_transfer=True):
    client.put("/api/v1/profile/exam-preparation", json={"exam_variant": variant})
    topic = "ielts-mh-academic" if variant == "academic" else "ielts-mh-general-training"
    session = client.post("/api/v1/sessions", json={
        "topic_id": topic, "exam_variant": variant, "question_type": "matching_headings",
    }).json()
    initial = session["current_question"]
    if variant == "academic":
        choices = ("ii", "iii", "v") if target == "main_idea_vs_detail" else ("ii", "i", "v")
    else:
        choices = ("i", "v", "iv") if target == "main_idea_vs_detail" else ("v", "i", "iv")
    result = _submit(client, session["id"], initial,
                     dict(zip(("paragraph-a", "paragraph-b", "paragraph-c"), choices)), prefix + "-initial")
    assert result["next_action"] == "diagnose"
    step = client.post(f"/api/v1/diagnoses/{result['diagnostic_case_id']}/step",
                       json={"idempotency_key": prefix + "-probe-dispatch"}).json()
    probe = step["next_question"]
    probe_answer = (
        {"probe-main": "probe-main-distractor", "probe-keyword": "probe-keyword-heading"}
        if target == "main_idea_vs_detail" else
        {"probe-main": "probe-main-heading", "probe-keyword": "probe-keyword-distractor"}
    )
    _submit(client, session["id"], probe, probe_answer, prefix + "-probe-answer")
    practice_dispatch = client.post(f"/api/v1/diagnoses/{result['diagnostic_case_id']}/step",
                                    json={"idempotency_key": prefix + "-practice-dispatch"}).json()
    practice = practice_dispatch["next_question"]
    practice_answer = _answer_for(factory, practice)
    assert _submit(client, session["id"], practice, practice_answer, prefix + "-practice-answer")["next_action"] == "matching_headings_transfer_pending"
    before = client.get(f"/api/v1/sessions/{session['id']}").json()
    assert before["status"] == "intervening" and before["can_dispatch_transfer"] is True
    if dispatch_transfer:
        dispatch = client.post(f"/api/v1/sessions/{session['id']}/transfer-check", json={"force_fresh": True})
        assert dispatch.status_code == 200, dispatch.text
        assert dispatch.json()["question"]["question_role"] == "transfer_check"
        assigned = client.get(f"/api/v1/sessions/{session['id']}").json()["current_question"]
        assert assigned["group_version_id"] != initial["group_version_id"]
        assert assigned["group_display"]["passage"]["id"] != initial["group_display"]["passage"]["id"]
    else:
        assigned = None
    return session, result, assigned


def test_matching_headings_transfer_and_delayed_review_success(phase4_client):
    client, factory, now = phase4_client
    session, initial_result, transfer = _reach_transfer(client, factory, "academic", "main_idea_vs_detail", "mh-a-success")
    transfer_answer = _answer_for(factory, transfer)
    scored = _submit(client, session["id"], transfer, transfer_answer, "mh-a-transfer")
    assert scored["is_correct"] is True and scored["next_action"] == "matching_headings_transfer_verified"
    replayed = _submit(client, session["id"], transfer, transfer_answer, "mh-a-transfer")
    assert replayed["attempt_id"] == scored["attempt_id"]
    with factory() as db:
        state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == "ielts-mh-academic"))
        case = db.get(DiagnosticCase, initial_result["diagnostic_case_id"])
        item = db.scalar(select(ReviewItem).where(ReviewItem.trigger_attempt_id == scored["attempt_id"]))
        transfer_attempt = db.get(Attempt, scored["attempt_id"])
        assert state.status == KnowledgeMasteryStatus.TRANSFER_VERIFIED.value
        assert state.last_transfer_attempt_id == transfer_attempt.id
        assert item.status == ReviewStatus.PENDING.value and item.retention_eligible
        assert item.trigger_attempt_id == transfer_attempt.id and item.group_version_id is not None and item.question_id is not None
        assert item.knowledge_state_id == state.id and item.hypothesis_id
        assert case.status == "resolved"
        assert db.scalar(select(EvidenceLink.id).where(EvidenceLink.attempt_id == transfer_attempt.id))
    reviews = client.get("/api/v1/reviews?status=pending").json()
    item = next(r for r in reviews if r["trigger_attempt_id"] == scored["attempt_id"])
    assert item["question_id"] and item["group_version_id"]
    assert item["retention_verified"] is False and item["is_due"] is False
    early = client.post(f"/api/v1/reviews/{item['id']}/start")
    assert early.status_code == 400
    no_ack = client.post(f"/api/v1/reviews/{item['id']}/complete", json={"review_notes": "done"})
    assert no_ack.status_code == 400
    now[0] += timedelta(days=1)
    with factory.begin() as db:
        q = db.get(Question, item["question_id"])
        old_group = db.get(ReadingGroupVersion, item["group_version_id"])
        key = db.get(ReadingRuleVersion, old_group.rule_version_id)
        display = deepcopy(old_group.display_json)
        display["passage"]["content_version"] = "2"
        display["passage"]["title"] += " — revised catalogue version"
        newer = import_matching_headings(
            db, display=display, private_rules=key.private_rules_json,
            exam_variant=old_group.exam_variant, provenance=old_group.provenance_json,
        )
        q.reading_group_version_id = newer.id
        assert newer.id != old_group.id
    # Concurrent start requests must converge on one review session and its pinned old group.
    with ThreadPoolExecutor(max_workers=2) as pool:
        started_responses = list(pool.map(lambda _: client.post(f"/api/v1/reviews/{item['id']}/start"), range(2)))
    assert all(r.status_code == 200 for r in started_responses)
    assert started_responses[0].json()["review_session_id"] == started_responses[1].json()["review_session_id"]
    started_json = started_responses[0].json()
    review_session = client.get(f"/api/v1/sessions/{started_json['review_session_id']}").json()
    review_question = review_session["current_question"]
    assert review_question["question_role"] == "review"
    assert review_question["group_version_id"] == item["group_version_id"]
    answer = _answer_for(factory, review_question)
    review_payload = {
        "question_id": review_question["id"], "group_version_id": review_question["group_version_id"],
        "structured_answer": answer, "idempotency_key": "mh-a-review",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicate_posts = list(pool.map(
            lambda _: client.post(f"/api/v1/sessions/{review_session['id']}/attempts", json=review_payload),
            range(2),
        ))
    assert all(response.status_code == 201 for response in duplicate_posts)
    assert duplicate_posts[0].json()["attempt_id"] == duplicate_posts[1].json()["attempt_id"]
    posted = duplicate_posts[0].json()
    assert posted["next_action"] == "matching_headings_retention_verified"
    finished = client.get(f"/api/v1/reviews/{item['id']}").json()
    assert finished["retention_verified"] is True
    assert finished["attempt_id"] == posted["attempt_id"]
    assert finished["group_version_id"] == review_question["group_version_id"]
    assert finished["trigger_attempt_id"] == scored["attempt_id"]
    with factory() as db:
        state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == "ielts-mh-academic"))
        assert state.status == KnowledgeMasteryStatus.TRANSFER_VERIFIED.value
        assert db.get(ReviewItem, item["id"]).retention_verified is True
        assert db.get(Attempt, posted["attempt_id"]).group_version_id == review_question["group_version_id"]


def test_transfer_pool_exhaustion_is_explicit_and_does_not_promote(phase4_client):
    client, factory, _now = phase4_client
    session, _initial, _ = _reach_transfer(
        client, factory, "academic", "main_idea_vs_detail", "mh-transfer-empty", dispatch_transfer=False,
    )
    with factory.begin() as db:
        candidates = db.scalars(select(Question).where(
            Question.topic_id == session["topic_id"], Question.question_role == QuestionRole.TRANSFER_CHECK.value,
        )).all()
        for question in candidates:
            question.question_role = QuestionRole.INITIAL.value
    response = client.post(f"/api/v1/sessions/{session['id']}/transfer-check", json={"force_fresh": True})
    assert response.status_code == 200 and response.json()["degraded"] is True
    assert response.json()["question"] is None and response.json()["next_action"] == "transfer_unavailable"
    with factory() as db:
        state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == session["topic_id"]))
        assert state.status == KnowledgeMasteryStatus.NEEDS_PRACTICE.value
        assert not db.scalar(select(Attempt.id).where(Attempt.session_id == session["id"], Attempt.attempt_role == QuestionRole.TRANSFER_CHECK.value))


def test_pre_correction_transfer_version_is_readable_but_cannot_create_mastery(phase4_client):
    client, factory, _now = phase4_client
    session, _initial, transfer = _reach_transfer(
        client, factory, "academic", "main_idea_vs_detail", "mh-old-content",
    )
    with factory.begin() as db:
        group = db.get(ReadingGroupVersion, transfer["group_version_id"])
        key = db.get(ReadingRuleVersion, group.rule_version_id)
        display = deepcopy(group.display_json)
        display["passage"]["content_version"] = "1"
        old_version = import_matching_headings(
            db, display=display, private_rules=key.private_rules_json,
            exam_variant=group.exam_variant, provenance=group.provenance_json,
        )
        db.get(LearningSession, session["id"]).current_group_version_id = old_version.id
        version_id = old_version.id
    restored = client.get(f"/api/v1/sessions/{session['id']}")
    assert restored.status_code == 200
    assert restored.json()["current_question"]["group_version_id"] == version_id
    response = client.post(f"/api/v1/sessions/{session['id']}/attempts", json={
        "question_id": transfer["id"], "group_version_id": version_id,
        "structured_answer": _answer_for(factory, transfer), "idempotency_key": "old-content-transfer",
    })
    assert response.status_code == 400
    assert "needs content correction" in response.text
    with factory() as db:
        assert not db.scalar(select(Attempt.id).where(
            Attempt.session_id == session["id"], Attempt.attempt_role == QuestionRole.TRANSFER_CHECK.value,
        ))
        state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == session["topic_id"]))
        assert state.status == KnowledgeMasteryStatus.NEEDS_PRACTICE.value


def test_matching_headings_history_uses_public_field_whitelist(phase4_client):
    from app.api.v1.schemas import LearningHistoryEventResponse

    client, factory, _now = phase4_client
    session, _, transfer = _reach_transfer(client, factory, "academic", "main_idea_vs_detail", "mh-history")
    _submit(client, session["id"], transfer, _answer_for(factory, transfer), "mh-history-transfer")
    response = client.get("/api/v1/profile/history?learner_id=default_learner")
    assert response.status_code == 200
    events = response.json()
    assert events
    allowed = set(LearningHistoryEventResponse.model_fields)
    for event in events:
        assert set(event) == allowed
        assert not {"standard_answer", "answer_explanation", "private_rules", "evaluation_rubric"} & set(event)
    for forbidden in ('"standard_answer"', '"private_rules"', '"evaluation_rubric"', '"distractors"'):
        assert forbidden not in response.text


def test_pre_correction_review_version_cannot_create_retention_evidence(phase4_client):
    client, factory, now = phase4_client
    session, _, transfer = _reach_transfer(client, factory, "academic", "main_idea_vs_detail", "mh-old-review")
    result = _submit(client, session["id"], transfer, _answer_for(factory, transfer), "mh-old-review-transfer")
    item = next(item for item in client.get("/api/v1/reviews?status=pending").json()
                if item["trigger_attempt_id"] == result["attempt_id"])
    now[0] += timedelta(days=1)
    started = client.post(f"/api/v1/reviews/{item['id']}/start").json()
    review_session_id = started["review_session_id"]
    review_question = client.get(f"/api/v1/sessions/{review_session_id}").json()["current_question"]
    answer = _answer_for(factory, review_question)
    with factory.begin() as db:
        group = db.get(ReadingGroupVersion, review_question["group_version_id"])
        rule = db.get(ReadingRuleVersion, group.rule_version_id)
        display = deepcopy(group.display_json)
        display["passage"]["content_version"] = "1"
        old_group = import_matching_headings(
            db, display=display, private_rules=rule.private_rules_json,
            exam_variant=group.exam_variant, provenance=group.provenance_json,
        )
        db.get(LearningSession, review_session_id).current_group_version_id = old_group.id
        db.get(ReviewItem, item["id"]).group_version_id = old_group.id
        old_id = old_group.id
    restored = client.get(f"/api/v1/sessions/{review_session_id}")
    assert restored.status_code == 200 and restored.json()["current_question"]["group_version_id"] == old_id
    response = client.post(f"/api/v1/sessions/{review_session_id}/attempts", json={
        "question_id": review_question["id"], "group_version_id": old_id,
        "structured_answer": answer, "idempotency_key": "old-content-review",
    })
    assert response.status_code == 400
    assert "needs content correction" in response.text
    with factory() as db:
        review = db.get(ReviewItem, item["id"])
        assert review.attempt_id is None and review.retention_verified is False
        assert not db.scalar(select(Attempt.id).where(Attempt.session_id == review_session_id))


def test_parallel_transfer_dispatch_converges_on_one_assignment(phase4_client):
    client, factory, _now = phase4_client
    session, _initial, _ = _reach_transfer(
        client, factory, "academic", "surface_keyword_matching", "mh-transfer-race", dispatch_transfer=False,
    )
    url = f"/api/v1/sessions/{session['id']}/transfer-check"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(url, json={"force_fresh": True}), range(2)))
    assert all(response.status_code == 200 for response in responses)
    ids = {response.json()["question"]["id"] for response in responses}
    assert len(ids) == 1
    with factory() as db:
        current = db.get(LearningSession, session["id"])
        case = db.scalar(select(DiagnosticCase).where(DiagnosticCase.session_id == session["id"]))
        events = [event for event in case.decision_events if event.action == "dispatch_matching_headings_transfer"]
        assert current.current_question_id in ids and len(events) == 1


def test_0005_to_0006_preserves_existing_review_item(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'phase4-upgrade.db').as_posix()}"
    settings = Settings(APP_ENV="testing", DATABASE_URL=database_url)
    engine = create_db_engine(settings)
    try:
        upgrade_database(database_url=database_url, engine=engine, revision="0005_reading_groups")
        with engine.begin() as connection:
            connection.execute(text("""INSERT INTO knowledge_topics
                (id,slug,domain_code,title,summary,difficulty_level,common_error_patterns,created_at,updated_at)
                VALUES ('topic_phase4_legacy','phase4-legacy','python','Legacy topic','Existing review data',1,'[]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""))
            connection.execute(text("""INSERT INTO review_items
                (id,learner_id,topic_id,trigger_reason,status,scheduled_for,created_at,review_stage,
                 retention_verified,retention_eligible)
                VALUES ('review_phase4_legacy','learner-legacy','topic_phase4_legacy','existing','pending',
                        '2026-01-01 00:00:00','2026-01-01 00:00:00',0,0,0)"""))
        upgrade_database(database_url=database_url, engine=engine)
        with engine.connect() as connection:
            row = connection.execute(text("SELECT id, trigger_attempt_id, group_version_id FROM review_items WHERE id='review_phase4_legacy'")).one()
            assert row == ("review_phase4_legacy", None, None)
            cols = {record["name"] for record in connection.execute(text("PRAGMA table_info(review_items)")).mappings()}
            assert {"trigger_attempt_id", "group_version_id"} <= cols
    finally:
        engine.dispose()


def test_review_pool_exhaustion_stays_pending(phase4_client):
    client, factory, now = phase4_client
    session, _initial, transfer = _reach_transfer(client, factory, "academic", "main_idea_vs_detail", "mh-review-empty")
    result = _submit(client, session["id"], transfer, _answer_for(factory, transfer), "mh-review-empty-transfer")
    pending = next(item for item in client.get("/api/v1/reviews?status=pending").json()
                   if item["trigger_attempt_id"] == result["attempt_id"])
    with factory.begin() as db:
        question = db.get(Question, pending["question_id"])
        question.question_role = QuestionRole.INITIAL.value
    now[0] += timedelta(days=1)
    unavailable = client.post(f"/api/v1/reviews/{pending['id']}/start")
    assert unavailable.status_code == 200
    body = unavailable.json()
    assert body["status"] == "pending" and body["review_session_id"] is None
    assert body["retention_verified"] is False and "没有未作答" in body["message"]
    with factory() as db:
        state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == session["topic_id"]))
        assert state.status == KnowledgeMasteryStatus.TRANSFER_VERIFIED.value
        assert db.get(ReviewItem, pending["id"]).attempt_id is None


@pytest.mark.parametrize(("variant", "target", "transfer_ok", "review_ok"), [
    ("academic", "surface_keyword_matching", False, None),
    ("general_training", "main_idea_vs_detail", True, False),
    ("general_training", "surface_keyword_matching", True, True),
])
def test_matching_headings_failure_and_variant_paths(phase4_client, variant, target, transfer_ok, review_ok):
    client, factory, now = phase4_client
    session, _initial_result, transfer = _reach_transfer(client, factory, variant, target, f"mh-{variant}-{target}")
    answer = _answer_for(factory, transfer)
    if transfer_ok is False:
        answer["item-1"], answer["item-2"] = answer["item-2"], answer["item-1"]
    transfer_result = _submit(client, session["id"], transfer, answer, f"mh-transfer-{variant}-{target}")
    if not transfer_ok:
        assert transfer_result["next_action"] == "matching_headings_transfer_failed_needs_practice"
        with factory() as db:
            state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == session["topic_id"]))
            assert state.status == KnowledgeMasteryStatus.NEEDS_PRACTICE.value
            assert not db.scalar(select(ReviewItem.id).where(ReviewItem.trigger_attempt_id == transfer_result["attempt_id"]))
        return
    assert transfer_result["next_action"] == "matching_headings_transfer_verified"
    with factory() as db:
        item = db.scalar(select(ReviewItem).where(ReviewItem.trigger_attempt_id == transfer_result["attempt_id"]))
        assert item is not None and item.retention_verified is False
        review_id = item.id
    now[0] += timedelta(days=1)
    started = client.post(f"/api/v1/reviews/{review_id}/start").json()
    review_session = client.get(f"/api/v1/sessions/{started['review_session_id']}").json()
    question = review_session["current_question"]
    answer = _answer_for(factory, question)
    if review_ok is False:
        answer["item-1"], answer["item-2"] = answer["item-2"], answer["item-1"]
    review_result = _submit(client, review_session["id"], question, answer, f"mh-review-{variant}-{target}")
    if review_ok:
        assert review_result["next_action"] == "matching_headings_retention_verified"
        assert client.get(f"/api/v1/reviews/{review_id}").json()["retention_verified"] is True
    else:
        assert review_result["next_action"] == "matching_headings_review_failed"
        review = client.get(f"/api/v1/reviews/{review_id}").json()
        assert review["retention_verified"] is False and review["review_outcome"] == "failed"
        with factory() as db:
            state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == session["topic_id"]))
            assert state.status == KnowledgeMasteryStatus.NEEDS_PRACTICE.value
            assert db.get(ReviewItem, review_id).attempt_id == review_result["attempt_id"]
