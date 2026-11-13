"""Independent transfer invariants through the real application and temporary SQLite."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.v1.dependencies import get_model_provider, get_session_factory
from app.config import get_settings
from app.domain.exceptions import DomainRuleViolationError
from app.domain.rules import transfer_context_key, validate_transfer_entry
from app.main import create_app
from app.model_provider import FakeModelProvider
from app.persistence.models import Attempt, DecisionEvent, Question
from app.persistence.seed import import_content_pack


@pytest.fixture
def transfer_client(session_factory, test_settings):
    with session_factory() as db:
        import_content_pack(db)
        db.commit()
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_model_provider] = lambda: FakeModelProvider(allow_default_fallback=True)
    with TestClient(app) as client:
        yield client


def post_answer(client, session_id, question_id, answer, key=None):
    return client.post(f"/api/v1/sessions/{session_id}/attempts", json={
        "question_id": question_id, "submitted_answer": answer, "idempotency_key": key,
    })


def practice_session(client, learner="transfer_learner"):
    session = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop", "learner_id": learner}).json()
    sid = session["id"]
    first = post_answer(client, sid, session["current_question_id"], "999").json()
    case_id = first["diagnostic_case_id"]
    step = client.post(f"/api/v1/diagnoses/{case_id}/step", json={"idempotency_key": f"{sid}-step-1"})
    assert step.status_code == 200, step.text
    assert step.json()["next_question"]["question_role"] == "diagnostic_followup"
    post_answer(client, sid, step.json()["next_question"]["id"], "尚不能确定，需要逐轮追踪。")
    second = client.post(f"/api/v1/diagnoses/{case_id}/step", json={"idempotency_key": f"{sid}-step-2"})
    assert second.status_code == 200, second.text
    assert second.json()["next_question"]["id"] == "q_py_loop_practice_01"
    return sid, case_id


@pytest.mark.parametrize("status,pending,required,passed", [
    ("active", True, False, False),
    ("diagnosing", False, True, False),
    ("intervening", True, True, True),
    ("paused", False, False, False),
    ("completed", False, False, False),
])
def test_domain_rejects_illegal_transfer_entry(status, pending, required, passed):
    with pytest.raises(DomainRuleViolationError):
        validate_transfer_entry(status, has_pending_question=pending,
                                practice_required=required, practice_passed=passed)


def test_context_freshness_compares_content_not_prompt_labels():
    assert transfer_context_key("different label", "print(1)\n") == transfer_context_key("original", " print(1) ")
    assert transfer_context_key("same task", "print(2)") != transfer_context_key("same task", "print(1)")
    validate_transfer_entry("transfer_checking", has_pending_question=False, practice_required=True, practice_passed=True)


def test_cannot_skip_initial_or_pending_targeted_practice(transfer_client):
    client = transfer_client
    created = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop"}).json()
    assert client.post(f"/api/v1/sessions/{created['id']}/transfer-check").status_code == 400
    sid, case = practice_session(client)
    before = client.get(f"/api/v1/sessions/{sid}").json()
    assert before["can_dispatch_transfer"] is False
    assert client.post(f"/api/v1/sessions/{sid}/transfer-check").status_code == 400
    assert client.post(f"/api/v1/diagnoses/{case}/step").status_code == 400
    after = client.get(f"/api/v1/sessions/{sid}").json()
    assert after["current_question_id"] == before["current_question_id"]
    assert after["attempts_count"] == 2


def test_failed_practice_retains_uncertainty_and_agent_assigns_new_practice(transfer_client):
    client = transfer_client
    sid, case = practice_session(client)
    # Regression: expected output 6 must not accept the prefix-matching answer 60.
    response = post_answer(client, sid, "q_py_loop_practice_01", "60", "failed-practice")
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["is_correct"] is False
    assert result["next_action"] == "diagnose_step"
    assert result["knowledge_state_status"] == "needs_practice"
    assert result["diagnostic_case_id"] == case
    assert client.get(f"/api/v1/diagnoses/{case}").json()["status"] == "needs_evidence"
    assert client.post(f"/api/v1/sessions/{sid}/transfer-check").status_code == 400
    assert post_answer(client, sid, "q_py_loop_practice_01", "6", "changed-intent").status_code == 400
    next_step = client.post(f"/api/v1/diagnoses/{case}/step").json()
    assert next_step["next_question"]["id"] == "q_py_loop_practice_02"
    assert post_answer(client, sid, "q_py_loop_practice_01", "60", "failed-practice").json() == result
    passed = post_answer(client, sid, "q_py_loop_practice_02", "8；逐轮加上 0、1、2、3。", "passed-practice").json()
    assert passed["next_action"] == "transfer_check"
    assert passed["knowledge_state_status"] != "stable"
    assert passed["next_question"]["question_role"] == "transfer_check"


def test_transfer_failure_old_question_retry_fresh_pass_and_immutable_replay(transfer_client, session_factory):
    client = transfer_client
    sid, case = practice_session(client)
    practice_payload = {"question_id": "q_py_loop_practice_01", "submitted_answer": "6", "idempotency_key": "practice-intent"}
    practice = client.post(f"/api/v1/sessions/{sid}/attempts", json=practice_payload).json()
    assert practice["next_action"] == "transfer_check"
    assert practice["next_question"]["id"] == "q_py_loop_transfer_01"
    assert client.get(f"/api/v1/diagnoses/{case}").json()["status"] == "transfer_checking"
    pending_dispatch = client.post(f"/api/v1/sessions/{sid}/transfer-check").json()
    assert pending_dispatch["question"]["id"] == "q_py_loop_transfer_01"
    failed = post_answer(client, sid, "q_py_loop_transfer_01", "3 15", "transfer-failed").json()
    assert failed["next_action"] == "transfer_failed_needs_practice"
    assert failed["diagnostic_case_id"] == case
    same = post_answer(client, sid, "q_py_loop_transfer_01", "3 17", "transfer-old-retry").json()
    assert same["next_action"] == "transfer_retry_blocked"
    assert same["knowledge_state_status"] != "stable"
    fresh = client.post(f"/api/v1/sessions/{sid}/transfer-check").json()
    assert fresh["question"]["id"] == "q_py_loop_transfer_02"
    assert client.post(f"/api/v1/sessions/{sid}/transfer-check").json()["question"] == fresh["question"]
    restored = client.get(f"/api/v1/sessions/{sid}").json()
    assert restored["current_question"] == fresh["question"]
    assert restored["active_diagnostic_case_id"] == case
    assert restored["latest_attempt_result"] == same
    passed = post_answer(client, sid, fresh["question"]["id"], "3 60", "transfer-passed").json()
    assert passed["knowledge_state_status"] == "stable"
    assert "长期保持尚未验证" in passed["mastery_note"]
    assert passed["evaluation_source"] == "rule_check"
    assert client.get(f"/api/v1/diagnoses/{case}").json()["status"] == "resolved"
    assert client.post(f"/api/v1/diagnoses/{case}/step").status_code == 400
    assert client.post(f"/api/v1/sessions/{sid}/complete").status_code == 200
    # A lost response can be recovered with the original key even after later work and completion.
    assert client.post(f"/api/v1/sessions/{sid}/attempts", json=practice_payload).json() == practice
    assert post_answer(client, sid, "q_py_loop_transfer_01", "3 15", "transfer-failed").json() == failed
    detail = client.get(f"/api/v1/attempts/{passed['attempt_id']}").json()
    assert detail["diagnostic_case_id"] == case
    assert detail["evaluation_source"] == "rule_check"
    evidence = client.get(f"/api/v1/diagnoses/{case}/evidence").json()
    assert any(item["attempt_id"] == passed["attempt_id"] and item["source_type"] == "transfer_attempt" for item in evidence)
    with session_factory() as db:
        attempt = db.get(Attempt, passed["attempt_id"])
        assert attempt.question_snapshot_json["question_id"] == "q_py_loop_transfer_02"
        event = db.scalars(select(DecisionEvent).where(DecisionEvent.action == "record_attempt_result", DecisionEvent.diagnostic_case_id == case)).all()
        assert len(event) == 6
        assert db.scalar(select(func.count()).select_from(Attempt).where(Attempt.session_id == sid)) == 6


def test_failed_transfer_can_return_to_targeted_intervention(transfer_client):
    client = transfer_client
    sid, case = practice_session(client)
    post_answer(client, sid, "q_py_loop_practice_01", "6")
    post_answer(client, sid, "q_py_loop_transfer_01", "999")
    next_step = client.post(f"/api/v1/diagnoses/{case}/step")
    assert next_step.status_code == 200, next_step.text
    assert next_step.json()["next_question"]["id"] == "q_py_loop_practice_02"
    passed = post_answer(client, sid, "q_py_loop_practice_02", "8").json()
    assert passed["next_question"]["id"] == "q_py_loop_transfer_02"
    assert passed["diagnostic_case_id"] == case


def test_new_ids_do_not_make_old_contexts_independent(transfer_client, session_factory):
    client = transfer_client
    with session_factory() as db:
        for original_id, alias in [("q_py_loop_initial_01", "a_initial_disguised_as_transfer"), ("q_py_loop_transfer_01", "b_transfer_copy")]:
            original = db.get(Question, original_id)
            db.add(Question(id=alias, topic_id=original.topic_id, question_role="transfer_check", question_type=original.question_type,
                            prompt_text="A renamed question", context_snippet=original.context_snippet,
                            standard_answer=original.standard_answer, answer_explanation=original.answer_explanation,
                            difficulty=1 if alias.startswith("a") else 4, version=1, evaluation_rubric=original.evaluation_rubric))
        db.commit()
    sid = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop"}).json()["id"]
    initial = post_answer(client, sid, "q_py_loop_initial_01", "3; add 0 then 1 then 2, tracking each iteration.").json()
    assert initial["next_question"]["id"] == "q_py_loop_transfer_01"
    post_answer(client, sid, "q_py_loop_transfer_01", "999")
    fresh = client.post(f"/api/v1/sessions/{sid}/transfer-check").json()
    assert fresh["question"]["id"] == "q_py_loop_transfer_02"
    post_answer(client, sid, "q_py_loop_transfer_02", "999")
    exhausted = client.post(f"/api/v1/sessions/{sid}/transfer-check").json()
    assert exhausted["degraded"] is True
    assert exhausted["question"] is None
    assert client.get(f"/api/v1/sessions/{sid}").json()["topic_mastered"] is False
    assert client.post(f"/api/v1/sessions/{sid}/transfer-check").json() == exhausted
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.session_id == sid, DecisionEvent.action == "transfer_questions_exhausted",
        )) == 1


def test_keys_cannot_cross_sessions_or_change_answers(transfer_client):
    client = transfer_client
    first = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop"}).json()["id"]
    second = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop"}).json()["id"]
    post_answer(client, first, "q_py_loop_initial_01", "999", "one-intent")
    assert post_answer(client, first, "q_py_loop_initial_01", "other answer", "one-intent").status_code == 409
    assert post_answer(client, second, "q_py_loop_initial_01", "999", "one-intent").status_code == 409
    assert client.get(f"/api/v1/sessions/{second}").json()["attempts_count"] == 0


def test_public_evidence_does_not_leak_private_expected_answer(transfer_client, session_factory):
    client = transfer_client
    marker = "PRIVATE_EXPECTED_OUTPUT_SENTINEL"
    with session_factory() as db:
        question = db.get(Question, "q_py_loop_initial_01")
        question.standard_answer = marker
        question.version += 1
        db.commit()
    sid = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop"}).json()["id"]
    result = post_answer(client, sid, "q_py_loop_initial_01", "999").json()
    case = result["diagnostic_case_id"]
    step = client.post(f"/api/v1/diagnoses/{case}/step").json()
    public = [result, step, client.get(f"/api/v1/diagnoses/{case}/evidence").json(), client.get(f"/api/v1/attempts/{result['attempt_id']}").json()]
    serialized = json.dumps(public)
    for secret in (marker, '"standard_answer"', '"evaluation_rubric"', '"answer_explanation"'):
        assert secret not in serialized


def test_new_error_supersedes_previous_stable_signal(transfer_client):
    client = transfer_client
    first = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop", "learner_id": "returning-learner"}).json()["id"]
    initial = post_answer(client, first, "q_py_loop_initial_01", "3; track each iteration adding 0 then 1 then 2.").json()
    assert initial["next_action"] == "transfer_check"
    assert client.get(f"/api/v1/sessions/{first}").json()["topic_mastered"] is False
    assert post_answer(client, first, "q_py_loop_transfer_01", "3 17").json()["knowledge_state_status"] == "stable"
    second = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop", "learner_id": "returning-learner"}).json()["id"]
    failed = post_answer(client, second, "q_py_loop_initial_01", "999").json()
    assert failed["knowledge_state_status"] == "needs_diagnosis"
    assert client.get(f"/api/v1/sessions/{second}").json()["topic_mastered"] is False


def test_concurrent_same_intent_records_one_attempt_and_one_case(transfer_client, session_factory):
    client = transfer_client
    sid = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop"}).json()["id"]
    barrier = Barrier(2)
    def send():
        barrier.wait(timeout=10)
        return post_answer(client, sid, "q_py_loop_initial_01", "999", "concurrent-intent")
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: send(), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt).where(Attempt.session_id == sid)) == 1
        assert db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.session_id == sid, DecisionEvent.action == "record_attempt_result",
        )) == 1


def test_exhausted_transfer_preserves_uncertainty_and_allows_more_intervention(transfer_client):
    client = transfer_client
    old = client.post("/api/v1/sessions", json={"topic_id": "py-for-loop", "learner_id": "exhausted-learner"}).json()["id"]
    post_answer(client, old, "q_py_loop_initial_01", "3; tracing each iteration adds 0 then 1 then 2.")
    post_answer(client, old, "q_py_loop_transfer_01", "999")
    client.post(f"/api/v1/sessions/{old}/transfer-check")
    post_answer(client, old, "q_py_loop_transfer_02", "999")
    sid, case = practice_session(client, "exhausted-learner")
    practice = post_answer(client, sid, "q_py_loop_practice_01", "6").json()
    assert practice["next_action"] == "transfer_unavailable"
    assert practice["next_question"] is None
    assert practice["knowledge_state_status"] == "insufficient_evidence"
    assert client.get(f"/api/v1/diagnoses/{case}").json()["status"] == "needs_evidence"
    assert client.get(f"/api/v1/sessions/{sid}").json()["topic_mastered"] is False
    step = client.post(f"/api/v1/diagnoses/{case}/step")
    assert step.status_code == 200, step.text
    assert step.json()["next_question"]["id"] == "q_py_loop_practice_02"
    post_answer(client, sid, "q_py_loop_practice_02", "999")
    exhausted = client.post(f"/api/v1/diagnoses/{case}/step")
    assert exhausted.status_code == 200, exhausted.text
    assert exhausted.json()["case_status"] == "insufficient_evidence"
    assert exhausted.json()["next_question"] is None
