import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.model_provider.fake import FakeModelProvider
from app.persistence.models import Attempt, DecisionEvent, KnowledgeState, ReadingGroupVersion, ReviewItem
from app.persistence.seed import import_content_pack
from tests.test_ielts_pivot import ielts_client  # noqa: F401

PACK = Path(__file__).parents[1] / "app/content/ielts_matching_headings_pack.json"


@pytest.fixture
def headings_client(ielts_client, session_factory, monkeypatch):
    def unexpected_model_call(*args, **kwargs):
        pytest.fail("Matching Headings scoring must not call a model")

    monkeypatch.setattr(FakeModelProvider, "generate_structured", unexpected_model_call)
    with session_factory.begin() as db:
        import_content_pack(db, pack_path=PACK)
        import_content_pack(db, pack_path=PACK)
        assert db.scalar(select(func.count()).select_from(ReadingGroupVersion)) == 2
    return ielts_client


def start(client, variant="academic"):
    assert client.put("/api/v1/profile/exam-preparation", json={"exam_variant": variant}).status_code == 200
    topic = "ielts-mh-academic" if variant == "academic" else "ielts-mh-general-training"
    response = client.post("/api/v1/sessions", json={
        "topic_id": topic, "exam_variant": variant, "question_type": "matching_headings",
    })
    assert response.status_code == 201, response.text
    assert not {"standard_answer", "answer_explanation", "evaluation_rubric"} & response.json()["current_question"].keys()
    return response.json()


def submit_payload(session, choices):
    return {
        "question_id": session["current_question_id"],
        "group_version_id": session["current_question"]["group_version_id"],
        "structured_answer": dict(zip(("paragraph-a", "paragraph-b", "paragraph-c"), choices)),
        "idempotency_key": session["id"],
    }


@pytest.mark.parametrize(("variant", "choices", "count", "outcome"), [
    ("academic", ("ii", "i", "iv"), 3, "correct"),
    ("academic", ("ii", "iii", "v"), 1, "partial"),
    ("general_training", ("v", "iii", "ii"), 3, "correct"),
    ("general_training", ("i", "iv", "iii"), 0, "incorrect"),
])
def test_scores_and_restores_groups(headings_client, session_factory, variant, choices, count, outcome):
    session = start(headings_client, variant)
    url = f"/api/v1/sessions/{session['id']}/attempts"
    body = submit_payload(session, choices)
    response = headings_client.post(url, json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    score = result["group_evaluation"]
    assert (score["correct_count"], score["total_count"], score["outcome"]) == (count, 3, outcome)
    assert sum(score["correct_by_item"].values()) == count
    assert result["is_correct"] is (count == 3)
    assert result["evaluation_source"] == "rule_check"
    assert score["content_version"] == score["evaluation_rule_version"] == "1"
    assert score["group_version_id"] == body["group_version_id"]
    replay = {**body, "structured_answer": dict(reversed(list(body["structured_answer"].items())))}
    assert headings_client.post(url, json=replay).json() == result
    assert headings_client.post(url, json={**body, "structured_answer": {**body["structured_answer"], "paragraph-a": "iv"}}).status_code == 409
    assert headings_client.get(url).json()[0]["group_evaluation"] == score
    detail = headings_client.get(f"/api/v1/attempts/{result['attempt_id']}").json()
    assert detail["structured_answer"] == body["structured_answer"]
    assert detail["group_evaluation"] == score
    if count < 3:
        assert result["next_action"] == "insufficient_evidence"
        case_url = f"/api/v1/diagnoses/{result['diagnostic_case_id']}"
        assert headings_client.get(case_url).json()["status"] == "insufficient_evidence"
        assert headings_client.get(case_url + "/hypotheses").json() == []
        assert headings_client.post(case_url + "/step", json={}).status_code == 400
    with session_factory() as db:
        attempt = db.get(Attempt, result["attempt_id"])
        assert attempt.structured_answer_json == body["structured_answer"]
        assert attempt.item_evaluation_json == score
        assert attempt.group_snapshot_json == session["current_question"]["group_display"]
        assert db.scalar(select(func.count()).select_from(ReviewItem)) == 0
        assert db.scalar(select(func.count()).select_from(KnowledgeState)) == 0
        assert db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.action == "record_attempt_result",
        )) == 1


def test_invalid_requests_do_not_write(headings_client, session_factory):
    session = start(headings_client)
    url = f"/api/v1/sessions/{session['id']}/attempts"
    body = submit_payload(session, ("ii", "i", "iv"))
    for changes, status in [
        ({"structured_answer": {"paragraph-a": "ii"}}, 400),
        ({"structured_answer": {"unknown": "ii", "paragraph-b": "i", "paragraph-c": "iv"}}, 400),
        ({"structured_answer": {"paragraph-a": "unknown", "paragraph-b": "i", "paragraph-c": "iv"}}, 400),
        ({"structured_answer": {"paragraph-a": "i", "paragraph-b": "i", "paragraph-c": "iv"}}, 400),
        ({"group_version_id": "wrong-version"}, 400),
        ({"question_id": "ielts-mh-gt-initial"}, 400),
        ({"submitted_answer": "ii"}, 422),
        ({"answer_key": {}}, 422),
    ]:
        response = headings_client.post(url, json={**body, **changes})
        assert response.status_code == status, response.text
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 0
        assert db.scalar(select(func.count()).select_from(DecisionEvent)) == 0
        assert db.scalar(select(func.count()).select_from(KnowledgeState)) == 0
    assert headings_client.get(f"/api/v1/sessions/{session['id']}").json()["status"] == "active"


def test_published_update_keeps_dispatched_scoring_rules(headings_client, session_factory):
    old = start(headings_client)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    group = pack["topics"][0]["questions"][0]["reading_group"]
    group["display"]["passage"]["content_version"] = "2"
    group["display"]["options"][0]["id"] = "vi"
    group["private_rules"]["rules_version"] = "2"
    group["private_rules"]["answers"]["paragraph-b"] = "vi"
    with session_factory.begin() as db:
        import_content_pack(db, pack_data=pack)
    current = start(headings_client)
    assert current["current_question"]["group_version_id"] != old["current_question"]["group_version_id"]
    restored = headings_client.get(f"/api/v1/sessions/{old['id']}").json()
    assert restored["current_question"] == old["current_question"]
    for session, choices, version in [(old, ("ii", "i", "iv"), "1"), (current, ("ii", "vi", "iv"), "2")]:
        response = headings_client.post(f"/api/v1/sessions/{session['id']}/attempts", json=submit_payload(session, choices))
        assert response.status_code == 201, response.text
        assert response.json()["is_correct"] is True
        assert response.json()["group_evaluation"]["evaluation_rule_version"] == version


@pytest.mark.parametrize("same_key", [True, False, None])
def test_concurrent_submissions_evaluate_once(headings_client, session_factory, same_key):
    session = start(headings_client)
    url = f"/api/v1/sessions/{session['id']}/attempts"
    first = submit_payload(session, ("ii", "iii", "v"))
    second = {**first}
    if same_key is None:
        del first["idempotency_key"]
        del second["idempotency_key"]
    elif not same_key:
        second["idempotency_key"] += "-other"
    barrier = Barrier(2, timeout=5)

    def submit(body):
        barrier.wait()
        return headings_client.post(url, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, (first, second)))
    expected = [201, 409] if same_key is False else [201, 201]
    assert sorted(response.status_code for response in responses) == expected
    if expected == [201, 201]:
        assert responses[0].json() == responses[1].json()
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 1
        assert db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.action == "record_attempt_result",
        )) == 1
