"""Verify Matching Headings Error DNA through real Uvicorn HTTP routes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from sqlalchemy import select

from app.persistence.models import (
    Attempt, DecisionEvent, DiagnosticCase, KnowledgeState, LearningSession,
    ModelCall, Question, ReadingGroupVersion, ReadingRuleVersion, ReviewItem,
)
from app.persistence.reading_groups import import_matching_headings
from scripts.verify_matching_headings_http import assert_public, run_acceptance

A = "main_idea_vs_detail"
B = "surface_keyword_matching"
ACADEMIC_TOPIC = "ielts-mh-academic"
GT_TOPIC = "ielts-mh-general-training"
ACADEMIC_PROBE = "ielts-mh-academic-diagnostic"
ACADEMIC_MAIN_PRACTICE = "ielts-mh-academic-main-practice"


def verify(client, factory):
    trace = {}
    group_sessions = {}

    def call(label, method, path, body=None, status=200):
        response = client.request(method, "/api/v1" + path, json=body) if body is not None else client.request(method, "/api/v1" + path)
        result = response.json()
        trace.setdefault(label, []).append({
            "method": method, "path": "/api/v1" + path, "request": body,
            "status": response.status_code, "request_id": response.headers.get("X-Request-ID"), "response": result,
        })
        assert response.status_code == status, (label, path, response.status_code, result)
        if response.is_success:
            assert_public(result)
            assert '"distractors"' not in response.text and '"task_versions"' not in response.text
        return result

    def create(label, variant="academic"):
        call(label, "PUT", "/profile/exam-preparation", {"exam_variant": variant})
        topic = ACADEMIC_TOPIC if variant == "academic" else GT_TOPIC
        session = call(label, "POST", "/sessions", {
            "topic_id": topic, "exam_variant": variant, "question_type": "matching_headings",
        }, 201)
        group_sessions[session["id"]] = label
        return session

    def submit(label, session, question, answer, key, status=201, **overrides):
        return call(label, "POST", f"/sessions/{session['id']}/attempts", {
            "question_id": question["id"], "group_version_id": question["group_version_id"],
            "structured_answer": answer, "idempotency_key": key, **overrides,
        }, status)

    def initial(label, choices=("ii", "iii", "v"), variant="academic"):
        session = create(label, variant)
        result = submit(label, session, session["current_question"], dict(zip(
            ("paragraph-a", "paragraph-b", "paragraph-c"), choices,
        )), session["id"] + "-initial")
        return session, result

    def step(label, result, key=None):
        return call(label, "POST", f"/diagnoses/{result['diagnostic_case_id']}/step", {"idempotency_key": key})

    def evidence(label, result):
        return call(label, "GET", f"/diagnoses/{result['diagnostic_case_id']}/evidence")

    def hypotheses(label, result):
        return {h["error_code"]: h for h in call(label, "GET", f"/diagnoses/{result['diagnostic_case_id']}/hypotheses")}

    main_answer = {"probe-main": "probe-main-distractor", "probe-keyword": "probe-keyword-heading"}
    keyword_answer = {"probe-main": "probe-main-heading", "probe-keyword": "probe-keyword-distractor"}

    for label, variant, choices, count, target, answer in [
        ("academic_main", "academic", ("ii", "iii", "v"), 1, A, main_answer),
        ("academic_keyword", "academic", ("ii", "i", "v"), 2, B, keyword_answer),
        ("gt_main", "general_training", ("i", "v", "iv"), 0, A, main_answer),
        ("gt_keyword", "general_training", ("v", "i", "iv"), 1, B, keyword_answer),
    ]:
        session, result = initial(label, choices, variant)
        assert result["group_evaluation"]["correct_count"] == count
        assert result["next_action"] == "diagnose"
        before = hypotheses(label, result)
        assert {h["status"] for h in before.values() if h["error_code"] in {A, B}} == {"candidate"}
        observations = evidence(label, result)
        assert len({e["observation"]["item_id"] for e in observations}) == 3 - count
        assert all(e["attempt_id"] == result["attempt_id"] and e["relation"] == "neutral" for e in observations)
        if label == "academic_main":
            assert len([e for e in observations if e["hypothesis_id"] == before[A]["id"]]) == 2
            assert len([e for e in observations if e["hypothesis_id"] == before[B]["id"]]) == 2
        follow = step(label, result, session["id"] + "-probe")
        assert follow["execution_mode"] == "rules" and follow["is_mock_provider"] is False
        assert follow["executed_tool"] == "select_diagnostic_followup"
        assert follow["next_question"]["id"] == f"ielts-mh-{'academic' if variant == 'academic' else 'gt'}-diagnostic"
        follow_result = submit(label, session, follow["next_question"], answer, session["id"] + "-probe-answer")
        assert follow_result["diagnostic_case_id"] == result["diagnostic_case_id"]
        after = hypotheses(label, result)
        other = B if target == A else A
        assert after[target]["status"] == "supported" and after[other]["status"] == "lowered"
        assert after[target]["confidence"] == 0.65 and after[other]["confidence"] == 0.2
        follow_evidence = [e for e in evidence(label, result) if e["attempt_id"] == follow_result["attempt_id"]]
        assert {(e["hypothesis_id"], e["relation"]) for e in follow_evidence} == {
            (after[target]["id"], "supports"), (after[other]["id"], "contradicts"),
        }
        expected_items = {"probe-main": after[A]["id"], "probe-keyword": after[B]["id"]}
        assert all(e["hypothesis_id"] == expected_items[e["observation"]["item_id"]] for e in follow_evidence)
        practice = step(label, result, session["id"] + "-practice")
        assert practice["executed_tool"] == "assign_targeted_practice"
        target_item = "main-practice" if target == A else "keyword-practice"
        assert practice["next_question"]["id"] == f"ielts-mh-{'academic' if variant == 'academic' else 'gt'}-{target_item}"
        assert practice["case_status"] == "intervention_selected"
        assert step(label, result, session["id"] + "-probe") == follow
        scored = submit(label, session, practice["next_question"],
                        {target_item: target_item + "-heading"}, session["id"] + "-practice-answer")
        assert scored["is_correct"] is True and scored["next_action"] == "matching_headings_transfer_pending"
        assert scored["knowledge_state_status"] is None
        restored = call(label, "GET", f"/sessions/{session['id']}")
        assert restored["status"] == "intervening" and restored["can_dispatch_transfer"] is True
        terminal = step(label, result, session["id"] + "-terminal")
        assert terminal["executed_tool"] == "matching_headings_transfer_pending" and terminal["next_question"] is None
        assert hypotheses(label, result)[target]["status"] == "supported"

    _, full = initial("all_correct", ("ii", "i", "iv"))
    assert full["is_correct"] and full["diagnostic_case_id"] is None
    _, unmapped = initial("unmapped", ("iii", "i", "iv"))
    assert set(hypotheses("unmapped", unmapped)) == {"insufficient_evidence"}
    assert step("unmapped", unmapped)["executed_tool"] == "matching_headings_insufficient_evidence"

    for label, answer in [
        ("neutral", {"probe-main": "probe-main-other", "probe-keyword": "probe-keyword-heading"}),
        ("both_supported", {"probe-main": "probe-main-distractor", "probe-keyword": "probe-keyword-distractor"}),
    ]:
        session, result = initial(label)
        follow = step(label, result)
        scored = submit(label, session, follow["next_question"], answer, session["id"] + "-probe-answer")
        relations = {e["relation"] for e in evidence(label, result) if e["attempt_id"] == scored["attempt_id"]}
        assert relations == ({"neutral", "contradicts"} if label == "neutral" else {"supports"})
        assert step(label, result)["next_question"] is None

    label = "practice_failed"
    session, result = initial(label)
    follow = step(label, result)
    submit(label, session, follow["next_question"], main_answer, session["id"] + "-probe-answer")
    practice = step(label, result)
    failed = submit(label, session, practice["next_question"],
                    {"main-practice": "main-practice-distractor"}, session["id"] + "-practice-answer")
    assert failed["next_action"] == "matching_headings_practice_incomplete"
    assert step(label, result)["next_question"] is None

    label = "dispatch_concurrency"
    session, result = initial(label)
    barrier = Barrier(2, timeout=5)

    def parallel_step(key):
        barrier.wait()
        return step(label, result, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(parallel_step, (session["id"] + "-first", session["id"] + "-second")))
    assert decisions[0] == decisions[1]
    follow = decisions[0]
    submit(label, session, follow["next_question"], main_answer, session["id"] + "-bad",
           status=400, group_version_id="wrong-rule-version")
    submit(label, session, follow["next_question"], main_answer, session["id"] + "-bad-type",
           status=400, question_id="q_py_var_initial_01")
    barrier.reset()

    def parallel_answer(_):
        barrier.wait()
        return submit(label, session, follow["next_question"], main_answer, session["id"] + "-probe-answer")

    with ThreadPoolExecutor(max_workers=2) as pool:
        scores = list(pool.map(parallel_answer, range(2)))
    assert scores[0] == scores[1]
    assert step(label, result, session["id"] + "-second") == follow
    assert step(label, result, session["id"] + "-practice")["executed_tool"] == "assign_targeted_practice"

    def alter_question(question_id, **changes):
        with factory.begin() as db:
            question = db.get(Question, question_id)
            old = {name: getattr(question, name) for name in changes}
            for name, value in changes.items():
                setattr(question, name, value)
            return old

    for label, changes in [
        ("followup_exhausted", {"question_role": "review"}),
        ("wrong_question_type", {"question_type": "multiple_choice"}),
    ]:
        _, result = initial(label)
        old = alter_question(ACADEMIC_PROBE, **changes)
        try:
            assert step(label, result)["executed_tool"] == "matching_headings_followup_unavailable"
        finally:
            alter_question(ACADEMIC_PROBE, **old)

    label = "wrong_exam_variant"
    _, result = initial(label)
    call(label, "POST", "/sessions", {"topic_id": GT_TOPIC, "exam_variant": "academic"}, 400)
    with factory() as db:
        wrong_version = db.get(Question, "ielts-mh-gt-diagnostic").reading_group_version_id
    old = alter_question(ACADEMIC_PROBE, reading_group_version_id=wrong_version)
    try:
        assert step(label, result)["executed_tool"] == "matching_headings_followup_unavailable"
    finally:
        alter_question(ACADEMIC_PROBE, **old)

    label = "wrong_rule_revision"
    _, result = initial(label)
    with factory.begin() as db:
        question = db.get(Question, ACADEMIC_PROBE)
        group = db.get(ReadingGroupVersion, question.reading_group_version_id)
        key = db.get(ReadingRuleVersion, group.rule_version_id)
        revised = import_matching_headings(
            db, display=group.display_json, exam_variant=group.exam_variant, provenance=group.provenance_json,
            private_rules={**key.private_rules_json, "rules_version": "unapproved-revision"},
        )
        revised_id = revised.id
    old = alter_question(ACADEMIC_PROBE, reading_group_version_id=revised_id)
    try:
        assert step(label, result)["executed_tool"] == "matching_headings_followup_unavailable"
    finally:
        alter_question(ACADEMIC_PROBE, **old)

    label = "practice_exhausted"
    session, result = initial(label)
    follow = step(label, result)
    submit(label, session, follow["next_question"], main_answer, session["id"] + "-probe-answer")
    old = alter_question(ACADEMIC_MAIN_PRACTICE, question_role="review")
    try:
        assert step(label, result)["executed_tool"] == "matching_headings_practice_unavailable"
    finally:
        alter_question(ACADEMIC_MAIN_PRACTICE, **old)

    label = "legacy"
    for topic, answer in [("topic_py_var_assign", "20 25"), ("ielts-tfng-acad-reading-english", "FALSE")]:
        session = call(label, "POST", "/sessions", {"topic_id": topic}, 201)
        result = call(label, "POST", f"/sessions/{session['id']}/attempts", {
            "question_id": session["current_question_id"], "submitted_answer": answer,
        }, 201)
        legacy_step = step(label, result, session["id"] + "-legacy")
        assert legacy_step["execution_mode"] == ("mock" if topic.startswith("topic_py") else "rules")

    snapshots = []
    with factory() as db:
        for session_id, label in group_sessions.items():
            session = db.get(LearningSession, session_id)
            attempts = db.scalars(select(Attempt).where(Attempt.session_id == session_id)).all()
            cases = db.scalars(select(DiagnosticCase).where(DiagnosticCase.session_id == session_id)).all()
            events = db.scalars(select(DecisionEvent).where(DecisionEvent.session_id == session_id)).all()
            assert len(cases) == (0 if label == "all_correct" else 1)
            assert len([event for event in events if event.action == "record_attempt_result"]) == len(attempts)
            assert not db.scalar(select(ModelCall.id).where(ModelCall.session_id == session_id))
            observation_events = [e for e in events if e.action == "observe_matching_heading_item"]
            assert len({(e.payload_json["observation"]["attempt_id"], e.payload_json["observation"]["item_id"])
                        for e in observation_events}) == len(observation_events)
            dispatches = [e for e in events if e.action in {"select_diagnostic_followup", "assign_targeted_practice"}]
            assert len({e.action for e in dispatches}) == len(dispatches)
            links = []
            for case in cases:
                for hypothesis in case.hypotheses:
                    assert hypothesis.status != "confirmed"
                    for link in hypothesis.evidence_links:
                        source = link.decision_event.payload_json["observation"]
                        attempt = next(a for a in attempts if a.id == source["attempt_id"])
                        assert (link.attempt_id, source["question_id"], source["group_version_id"], source["rule_version_id"]) == (
                            attempt.id, attempt.question_id, attempt.group_version_id, attempt.item_evaluation_json["rule_version_id"],
                        )
                        links.append({"id": link.id, "hypothesis_id": hypothesis.id, "relation": link.relation,
                                      "decision_event_id": link.decision_event_id, "source_ref": link.source_ref, "source": source})
            snapshots.append({
                "scenario": label, "session_id": session_id, "session_status": session.status,
                "attempts": [{"id": a.id, "question_id": a.question_id, "role": a.attempt_role,
                              "group_version_id": a.group_version_id, "evaluation": a.item_evaluation_json} for a in attempts],
                "cases": [{"id": c.id, "trigger_attempt_id": c.trigger_attempt_id, "status": c.status,
                           "hypotheses": [{"id": h.id, "error_code": h.error_code, "status": h.status} for h in c.hypotheses]}
                          for c in cases],
                "evidence_links": links,
                "decision_events": [{"id": e.id, "case_id": e.diagnostic_case_id, "action": e.action,
                                     "payload": e.payload_json} for e in observation_events + dispatches],
            })
        states = db.scalars(select(KnowledgeState).where(KnowledgeState.topic_id.in_([ACADEMIC_TOPIC, GT_TOPIC]))).all()
        assert states and all(state.status == "needs_practice" for state in states)
        assert not db.scalar(select(ReviewItem.id).where(ReviewItem.topic_id.in_([ACADEMIC_TOPIC, GT_TOPIC])))
    return {"server": "Uvicorn + FastAPI", "database": "isolated SQLite, Alembic 0005",
            "requests": trace, "database_evidence": snapshots,
            "matching_headings_knowledge_state_count": len(states), "matching_headings_review_count": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run_acceptance(verify, parser.parse_args().output)
