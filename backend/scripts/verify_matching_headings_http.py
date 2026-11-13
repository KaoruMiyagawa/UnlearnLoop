"""Run Phase 2 acceptance over a loopback Uvicorn server and disposable SQLite."""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
from sqlalchemy import func, select

from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database
from app.persistence.models import Attempt, DecisionEvent, DiagnosticCase, KnowledgeState, LearningSession, ReviewItem
from app.persistence.seed import import_content_pack

BACKEND = Path(__file__).resolve().parents[1]
PACK = BACKEND / "app/content/ielts_matching_headings_pack.json"
PRIVATE_FIELDS = {
    "standard_answer", "answer_explanation", "evaluation_rubric",
    "private_rules", "private_rules_json", "answers", "explanations",
}


def assert_public(value):
    if isinstance(value, dict):
        assert not (PRIVATE_FIELDS & value.keys()), PRIVATE_FIELDS & value.keys()
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


def verify(client, factory):
    trace = {}
    group_sessions = {}

    def call(label, method, path, body=None, expected=200):
        kwargs = {} if body is None else {"json": body}
        response = client.request(method, "/api/v1" + path, **kwargs)
        record = {
            "method": method, "path": "/api/v1" + path, "request": body,
            "status": response.status_code, "request_id": response.headers.get("X-Request-ID"),
            "response": response.json(),
        }
        trace.setdefault(label, []).append(record)
        allowed = expected if isinstance(expected, tuple) else (expected,)
        assert response.status_code in allowed, record
        if response.is_success:
            assert_public(record["response"])
        return record["response"], response.status_code

    def start(label, variant):
        call(label, "PUT", "/profile/exam-preparation", {"exam_variant": variant})
        topic = "ielts-mh-academic" if variant == "academic" else "ielts-mh-general-training"
        session, _ = call(label, "POST", "/sessions", {
            "topic_id": topic, "exam_variant": variant, "question_type": "matching_headings",
        }, 201)
        question = session["current_question"]
        assert question["question_type"] == "matching_headings"
        assert len(question["group_display"]["passage"]["paragraphs"]) == 3
        assert len(question["group_display"]["options"]) == 5
        group_sessions[session["id"]] = label
        return session

    def body(session, choices=("ii", "i", "iv")):
        return {
            "question_id": session["current_question_id"],
            "group_version_id": session["current_question"]["group_version_id"],
            "structured_answer": dict(zip(("paragraph-a", "paragraph-b", "paragraph-c"), choices)),
            "idempotency_key": session["id"],
        }

    def attempt_path(session):
        return f"/sessions/{session['id']}/attempts"

    for label, variant, choices, outcome, count in [
        ("A_academic_correct", "academic", ("ii", "i", "iv"), "correct", 3),
        ("B_academic_partial", "academic", ("ii", "iii", "v"), "partial", 1),
        ("C_gt_correct", "general_training", ("v", "iii", "ii"), "correct", 3),
        ("D_gt_incorrect", "general_training", ("i", "iv", "iii"), "incorrect", 0),
    ]:
        session = start(label, variant)
        qid = session["current_question_id"]
        call(label, "GET", f"/questions/{qid}")
        result, _ = call(label, "POST", attempt_path(session), body(session, choices), 201)
        evaluation = result["group_evaluation"]
        assert (evaluation["outcome"], evaluation["correct_count"], evaluation["total_count"]) == (outcome, count, 3)
        assert result["is_correct"] is (count == 3)
        assert result["evaluation_source"] == "rule_check"
        assert call(label, "GET", f"/attempts/{result['attempt_id']}")[0]["group_evaluation"] == evaluation
        assert call(label, "GET", attempt_path(session))[0][0]["group_evaluation"] == evaluation
        if count < 3:
            case_path = f"/diagnoses/{result['diagnostic_case_id']}"
            assert call(label, "GET", case_path)[0]["status"] == "insufficient_evidence"
            assert call(label, "GET", case_path + "/hypotheses")[0] == []
            call(label, "POST", case_path + "/step", {}, 400)
        assert call(label, "GET", f"/sessions/{session['id']}")[0]["can_dispatch_transfer"] is False

    label = "E_invalid"
    invalid = start(label, "academic")
    path = attempt_path(invalid)
    initial = body(invalid)
    for changes, status in [
        ({"group_version_id": "wrong"}, 400),
        ({"structured_answer": {"paragraph-a": "ii"}}, 400),
        ({"structured_answer": {"unknown": "ii", "paragraph-b": "i", "paragraph-c": "iv"}}, 400),
        ({"structured_answer": {"paragraph-a": "unknown", "paragraph-b": "i", "paragraph-c": "iv"}}, 400),
        ({"structured_answer": {"paragraph-a": "i", "paragraph-b": "i", "paragraph-c": "iv"}}, 400),
        ({"question_id": "ielts-mh-gt-initial"}, 400),
        ({"submitted_answer": "ii"}, 422),
        ({"answer_key": {}}, 422),
    ]:
        call(label, "POST", path, {**initial, **changes}, status)
    assert call(label, "GET", path)[0] == []
    assert call(label, "GET", f"/sessions/{invalid['id']}")[0]["status"] == "active"

    label = "F_replay"
    session = start(label, "academic")
    path = attempt_path(session)
    submitted = body(session)
    original, _ = call(label, "POST", path, submitted, 201)
    reordered = dict(reversed(list(submitted["structured_answer"].items())))
    assert call(label, "POST", path, {**submitted, "structured_answer": reordered}, 201)[0] == original
    call(label, "POST", path, {**submitted, "structured_answer": body(session, ("ii", "iii", "v"))["structured_answer"]}, 409)

    label = "F_discarded_response"
    session = start(label, "academic")
    path = attempt_path(session)
    submitted = body(session)
    with client.stream("POST", "/api/v1" + path, json=submitted) as response:
        assert response.status_code == 201
        trace[label].append({
            "method": "POST", "path": "/api/v1" + path, "request": submitted,
            "status": response.status_code, "request_id": response.headers.get("X-Request-ID"),
            "response_body_read": False,
        })
    with factory() as db:
        original_id = db.scalar(select(Attempt.id).where(Attempt.session_id == session["id"]))
    retry, _ = call(label, "POST", path, submitted, 201)
    assert retry["attempt_id"] == original_id

    for mode in ("same_key", "different_keys", "no_keys"):
        label = "F_concurrent_" + mode
        session = start(label, "academic")
        path = attempt_path(session)
        first = body(session, ("ii", "iii", "v"))
        second = {**first}
        if mode == "different_keys":
            second["idempotency_key"] += "-different"
        elif mode == "no_keys":
            del first["idempotency_key"]
            del second["idempotency_key"]
        barrier = Barrier(2, timeout=5)

        def concurrent(payload):
            barrier.wait()
            return call(label, "POST", path, payload, (201, 409))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(concurrent, (first, second)))
        statuses = sorted(status for _, status in results)
        assert statuses == ([201, 409] if mode == "different_keys" else [201, 201])
        if statuses == [201, 201]:
            assert results[0][0] == results[1][0]
        assert len(call(label, "GET", path)[0]) == 1

    label = "G_version_update"
    old = start(label, "academic")
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    group = pack["topics"][0]["questions"][0]["reading_group"]
    group["display"]["passage"]["content_version"] = "2"
    group["display"]["options"][0]["id"] = "vi"
    group["private_rules"]["rules_version"] = "2"
    group["private_rules"]["answers"]["paragraph-b"] = "vi"
    with factory.begin() as db:
        import_content_pack(db, pack_data=pack)
    new = start(label, "academic")
    assert old["current_question"]["group_version_id"] != new["current_question"]["group_version_id"]
    assert call(label, "GET", f"/sessions/{old['id']}")[0]["current_question"] == old["current_question"]
    call(label, "POST", attempt_path(old), {**body(old), "group_version_id": new["current_question"]["group_version_id"]}, 400)
    for session, choices, version in [(old, ("ii", "i", "iv"), "1"), (new, ("ii", "vi", "iv"), "2")]:
        result, _ = call(label, "POST", attempt_path(session), body(session, choices), 201)
        assert result["is_correct"] and result["group_evaluation"]["evaluation_rule_version"] == version

    label = "H_legacy"
    call(label, "PUT", "/profile/exam-preparation", {"exam_variant": "academic"})
    for topic, answer in [("topic_py_var_assign", "20 15 because b was calculated before a changed."),
                          ("ielts-tfng-acad-reading-english", "FALSE")]:
        session, _ = call(label, "POST", "/sessions", {"topic_id": topic}, 201)
        legacy = {"question_id": session["current_question_id"], "submitted_answer": answer,
                  "idempotency_key": session["id"]}
        call(label, "POST", attempt_path(session), {
            "question_id": session["current_question_id"], "group_version_id": "unassigned",
            "structured_answer": {"paragraph-a": "i"}, "idempotency_key": session["id"],
        }, 400)
        result, _ = call(label, "POST", attempt_path(session), legacy, 201)
        assert result["group_evaluation"] is None
        assert call(label, "POST", attempt_path(session), legacy, 201)[0] == result
        if topic.startswith("ielts-"):
            step, _ = call(label, "POST", f"/diagnoses/{result['diagnostic_case_id']}/step", {})
            assert step["execution_mode"] == "rules"
        else:
            assert result["is_correct"]

    snapshots = []
    with factory() as db:
        for session_id, label in group_sessions.items():
            session = db.get(LearningSession, session_id)
            attempts = db.scalars(select(Attempt).where(Attempt.session_id == session_id)).all()
            result_count = db.scalar(select(func.count()).select_from(DecisionEvent).where(
                DecisionEvent.session_id == session_id, DecisionEvent.action == "record_attempt_result",
            ))
            case_count = db.scalar(select(func.count()).select_from(DiagnosticCase).where(DiagnosticCase.session_id == session_id))
            assert len(attempts) == result_count == (0 if label == "E_invalid" else 1)
            snapshot = {
                "scenario": label, "session_id": session_id, "session_status": session.status,
                "pinned_group_version_id": session.current_group_version_id,
                "attempt_count": len(attempts), "result_event_count": result_count, "diagnostic_case_count": case_count,
            }
            if attempts:
                attempt = attempts[0]
                assert attempt.group_version_id == session.current_group_version_id
                assert case_count == int(not attempt.is_correct)
                snapshot.update({
                    "attempt_id": attempt.id, "structured_answer_json": attempt.structured_answer_json,
                    "item_evaluation_json": attempt.item_evaluation_json,
                    "snapshot_passage_content_version": attempt.group_snapshot_json["passage"]["content_version"],
                    "evaluation_rule_version": attempt.evaluation_rule_version,
                })
            snapshots.append(snapshot)
        for model in (KnowledgeState, ReviewItem):
            assert db.scalar(select(func.count()).select_from(model).where(
                model.topic_id.in_(["ielts-mh-academic", "ielts-mh-general-training"]),
            )) == 0
    return {
        "server": "Uvicorn + FastAPI on loopback", "database": "isolated temporary SQLite, Alembic 0005",
        "requests": trace, "database_evidence": snapshots,
        "matching_headings_knowledge_state_count": 0, "matching_headings_review_count": 0,
    }


def run_acceptance(verify_scenarios, output, *, phase_two=False):
    output = output.resolve()
    with tempfile.TemporaryDirectory(prefix="verbatrail-2b1-http-") as temp:
        db_path = Path(temp) / "acceptance.sqlite"
        db_url = f"sqlite:///{db_path.as_posix()}"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {**os.environ, "APP_ENV": "testing" if phase_two else "development", "DATABASE_URL": db_url,
               "MODEL_PROVIDER": "fake", "ALLOW_REMOTE_MODEL_CALLS": "false", "MODEL_API_KEY": ""}
        log_path = Path(temp) / "uvicorn.log"
        engine = create_db_engine(database_url=db_url)
        factory = create_session_factory(engine)
        if phase_two:
            # Reproduce the old publication rather than the current startup seed.
            upgrade_database(engine=engine, database_url=db_url)
            with factory.begin() as db:
                import_content_pack(db)
                for name in ("ielts_reading_pack.json", "ielts_reading_english_pack.json",
                             "ielts_tfng_diagnostic_pack.json", PACK.name):
                    import_content_pack(db, pack_path=PACK.parent / name)
        with log_path.open("wb") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=BACKEND, env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
                    deadline = time.monotonic() + 20
                    while True:
                        if server.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError("Isolated Uvicorn did not start.")
                        try:
                            if client.get("/openapi.json").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.1)
                    evidence = verify_scenarios(client, factory)
            except Exception:
                print(log_path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
                raise
            finally:
                engine.dispose()
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=10)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Saved {sum(map(len, evidence['requests'].values()))} HTTP records to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run_acceptance(verify, parser.parse_args().output, phase_two=True)


if __name__ == "__main__":
    main()
