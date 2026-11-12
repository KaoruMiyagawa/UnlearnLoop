"""Phase 3 API and version pinning regressions on isolated SQLite."""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.persistence.models import Attempt, ModelCall, Question, ReadingGroupVersion, ReadingRuleVersion
from app.persistence.reading_groups import import_matching_headings
from app.persistence.seed import import_content_pack, load_matching_headings_diagnostic_pack
from scripts.verify_matching_headings_diagnostics_http import verify
from tests.test_ielts_pivot import ielts_client  # noqa: F401


@pytest.fixture
def diagnostic_client(ielts_client, session_factory):
    with session_factory.begin() as db:
        import_content_pack(db, pack_data=load_matching_headings_diagnostic_pack(db))
        import_content_pack(db, pack_path=Path(__file__).parents[1] / "app/content/ielts_tfng_diagnostic_pack.json")
    return ielts_client


def test_error_dna_and_targeted_practice_protocol(diagnostic_client, session_factory):
    evidence = verify(diagnostic_client, session_factory)
    assert evidence["matching_headings_knowledge_state_count"] == 2
    assert evidence["matching_headings_review_count"] == 0


def start(client):
    assert client.put("/api/v1/profile/exam-preparation", json={"exam_variant": "academic"}).status_code == 200
    response = client.post("/api/v1/sessions", json={
        "topic_id": "ielts-mh-academic", "question_type": "matching_headings",
    })
    assert response.status_code == 201
    return response.json()


def submit(client, session, question, answers):
    response = client.post(f"/api/v1/sessions/{session['id']}/attempts", json={
        "question_id": question["id"], "group_version_id": question["group_version_id"], "structured_answer": answers,
    })
    assert response.status_code == 201, response.text
    return response.json()


def publish_revision(factory, question_id, revision):
    with factory.begin() as db:
        question = db.get(Question, question_id)
        group = db.get(ReadingGroupVersion, question.reading_group_version_id)
        key = db.get(ReadingRuleVersion, group.rule_version_id)
        revised = import_matching_headings(
            db, display=group.display_json, exam_variant=group.exam_variant, provenance=group.provenance_json,
            private_rules=revision(key.private_rules_json),
        )
        question.reading_group_version_id = revised.id
        return revised.id


def test_dispatched_probe_and_old_step_keep_the_original_version(diagnostic_client, session_factory):
    client = diagnostic_client
    session = start(client)
    first = submit(client, session, session["current_question"], {
        "paragraph-a": "ii", "paragraph-b": "iii", "paragraph-c": "v",
    })
    path = f"/api/v1/diagnoses/{first['diagnostic_case_id']}/step"
    probe = client.post(path, json={"idempotency_key": "probe"}).json()
    q = probe["next_question"]
    newer = publish_revision(session_factory, q["id"], lambda old: {**old, "rules_version": "next"})
    assert newer != q["group_version_id"]
    restored = client.get(f"/api/v1/sessions/{session['id']}").json()["current_question"]
    assert restored["group_version_id"] == q["group_version_id"]
    score = submit(client, session, q, {
        "probe-main": "probe-main-heading", "probe-keyword": "probe-keyword-distractor",
    })
    assert score["group_evaluation"]["evaluation_rule_version"] == "1"
    assert client.post(path, json={"idempotency_key": "practice"}).json()["executed_tool"] == "assign_targeted_practice"
    assert client.post(path, json={"idempotency_key": "probe"}).json() == probe


def test_unknown_initial_protocol_fails_closed(diagnostic_client, session_factory):
    client = diagnostic_client
    publish_revision(session_factory, "ielts-mh-academic-initial", lambda old: {
        **old, "rules_version": "unknown", "diagnostics": {**old["diagnostics"], "version": "999"},
    })
    session = start(client)
    first = submit(client, session, session["current_question"], {
        "paragraph-a": "ii", "paragraph-b": "iii", "paragraph-c": "v",
    })
    case_path = f"/api/v1/diagnoses/{first['diagnostic_case_id']}"
    case = client.get(case_path).json()
    assert case["execution_mode"] == "unavailable" and case["status"] == "insufficient_evidence"
    assert case["hypotheses"] == []
    assert client.post(case_path + "/step", json={}).status_code == 400
    with session_factory() as db:
        assert db.get(Attempt, first["attempt_id"]).question_snapshot_json["diagnostic_version"] == "999"
        assert db.scalar(select(ModelCall.id).where(ModelCall.session_id == session["id"])) is None
