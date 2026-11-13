"""Real Uvicorn/FastAPI acceptance for Matching Headings transfer and delayed review.

Uses an isolated migrated SQLite database, a loopback HTTP client and an injected
clock. The persisted evidence contains requests/results and linked record IDs,
never the private answer keys or diagnostic maps.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Thread
import time
from typing import Any

import httpx
import uvicorn
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    clear_engine_cache,
    get_db,
    get_learning_service,
    get_or_create_engine_and_factory,
)
from app.application.learning_service import LearningAppService
from app.config import Settings, get_settings
from app.domain.enums import QuestionRole
from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database
from app.persistence.models import (
    Attempt,
    DiagnosticCase,
    EvidenceLink,
    KnowledgeState,
    LearningSession,
    Question,
    ReadingGroupVersion,
    ReadingRuleVersion,
    ReviewItem,
)
from app.persistence.reading_groups import import_matching_headings
from app.persistence.seed import import_content_pack, load_matching_headings_diagnostic_pack

BACKEND_DIR = Path(__file__).resolve().parents[1]
ACADEMIC = "ielts-mh-academic"
GENERAL = "ielts-mh-general-training"


class ControlledClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 4, 1, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, days: int = 0, hours: int = 0) -> None:
        self.value += timedelta(days=days, hours=hours)


def _seed(factory) -> None:
    with factory.begin() as db:
        import_content_pack(db)
        import_content_pack(db, pack_path=BACKEND_DIR / "app/content/ielts_reading_pack.json")
        import_content_pack(db, pack_path=BACKEND_DIR / "app/content/ielts_reading_english_pack.json")
        import_content_pack(db, pack_path=BACKEND_DIR / "app/content/ielts_tfng_diagnostic_pack.json")
        import_content_pack(db, pack_data=load_matching_headings_diagnostic_pack(db))


def run_acceptance(output_path: Path | None = None) -> dict[str, Any]:
    trace: dict[str, list[dict[str, Any]]] = {}
    database_snapshot: list[dict[str, Any]] = []
    clock = ControlledClock()

    with TemporaryDirectory(prefix="verbatrail-mh-phase4-") as temp_dir:
        db_path = Path(temp_dir) / "phase4.sqlite3"
        settings = Settings(
            APP_NAME="VerbaTrail isolated IELTS-2B.1 Phase 4",
            APP_ENV="testing",
            DATABASE_URL=f"sqlite:///{db_path.as_posix()}",
            MODEL_PROVIDER="fake",
            MODEL_API_KEY="",
            ALLOW_REMOTE_MODEL_CALLS=False,
            REVIEW_INTERVALS_DAYS=(1, 3),
        )
        engine = create_db_engine(settings)
        upgrade_database(database_url=settings.database_url, engine=engine)
        factory = create_session_factory(engine)
        _seed(factory)

        from app.main import create_app

        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        def learning_service(db: Session = Depends(get_db), resolved: Settings = Depends(get_settings)):
            return LearningAppService(db, settings=resolved, clock=clock)

        app.dependency_overrides[get_learning_service] = learning_service
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = Thread(target=server.run, name="phase4-uvicorn", daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                if not thread.is_alive():
                    raise RuntimeError("Uvicorn exited before startup completed")
                time.sleep(0.05)
            if not server.started:
                raise TimeoutError("Uvicorn did not start")

            base = f"http://127.0.0.1:{port}/api/v1"
            client = httpx.Client(base_url=base, timeout=15, trust_env=False)

            def request(label: str, method: str, path: str, body: dict | None = None,
                        *, params: dict | None = None, expected: int = 200):
                response = client.request(method, path, json=body, params=params)
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"text": response.text}
                trace.setdefault(label, []).append({
                    "method": method, "path": path, "request": body, "query": params,
                    "status": response.status_code, "request_id": response.headers.get("X-Request-ID"),
                    "response": payload,
                })
                if response.status_code != expected:
                    raise AssertionError(f"{label} {method} {path}: {response.status_code}: {payload}")
                if response.is_success:
                    serialized = json.dumps(payload, ensure_ascii=False)
                    if any(secret in serialized for secret in ("distractors", "task_versions", "private_rules", "standard_answer")):
                        raise AssertionError("A public Matching Headings response included private rules")
                return payload

            def private_answers(question: dict) -> dict[str, str]:
                with factory() as db:
                    version = db.get(ReadingGroupVersion, question["group_version_id"])
                    rule = db.get(ReadingRuleVersion, version.rule_version_id)
                    return dict(rule.private_rules_json["answers"])

            def publish_new_group_revision(question: dict) -> str:
                """Publish changed immutable content while an old assignment remains pinned."""
                with factory.begin() as db:
                    question_row = db.get(Question, question["id"])
                    old = db.get(ReadingGroupVersion, question["group_version_id"])
                    private = db.get(ReadingRuleVersion, old.rule_version_id)
                    display = deepcopy(old.display_json)
                    display["passage"]["content_version"] = str(int(display["passage"]["content_version"]) + 1)
                    display["passage"]["title"] += " — revised content version"
                    display["passage"]["paragraphs"][0]["text"] += " The later catalogue release adds this distinct editorial sentence."
                    newer = import_matching_headings(
                        db, display=display, private_rules=private.private_rules_json,
                        exam_variant=old.exam_variant, provenance=old.provenance_json,
                    )
                    question_row.reading_group_version_id = newer.id
                    return newer.id

            def submit(label: str, session_id: str, question: dict, answers: dict, key: str):
                return request(label, "POST", f"/sessions/{session_id}/attempts", {
                    "question_id": question["id"], "group_version_id": question["group_version_id"],
                    "structured_answer": answers, "idempotency_key": key,
                }, expected=201)

            def reach_transfer(label: str, variant: str, target: str, learner: str,
                               *, concurrency: bool = False, dispatch_transfer: bool = True):
                request(label, "PUT", "/profile/exam-preparation", {"exam_variant": variant},
                        params={"learner_id": learner})
                topic = ACADEMIC if variant == "academic" else GENERAL
                session = request(label, "POST", "/sessions", {
                    "topic_id": topic, "learner_id": learner, "exam_variant": variant,
                    "question_type": "matching_headings",
                }, expected=201)
                initial = session["current_question"]
                if variant == "academic":
                    choices = ("ii", "iii", "v") if target == "main_idea_vs_detail" else ("ii", "i", "v")
                else:
                    choices = ("i", "v", "iv") if target == "main_idea_vs_detail" else ("v", "i", "iv")
                wrong = dict(zip(("paragraph-a", "paragraph-b", "paragraph-c"), choices))
                original = submit(label, session["id"], initial, wrong, learner + "-initial")
                probe = request(label, "POST", f"/diagnoses/{original['diagnostic_case_id']}/step",
                                {"idempotency_key": learner + "-probe-dispatch"})["next_question"]
                probe_answers = (
                    {"probe-main": "probe-main-distractor", "probe-keyword": "probe-keyword-heading"}
                    if target == "main_idea_vs_detail" else
                    {"probe-main": "probe-main-heading", "probe-keyword": "probe-keyword-distractor"}
                )
                submit(label, session["id"], probe, probe_answers, learner + "-probe-answer")
                practice = request(label, "POST", f"/diagnoses/{original['diagnostic_case_id']}/step",
                                   {"idempotency_key": learner + "-practice-dispatch"})["next_question"]
                practice_answers = private_answers(practice)
                submit(label, session["id"], practice, practice_answers, learner + "-practice-answer")
                restored = request(label, "GET", f"/sessions/{session['id']}")
                if restored["status"] != "intervening" or not restored["can_dispatch_transfer"]:
                    raise AssertionError("Successful practice did not authorize the Matching Headings transfer step")
                if not dispatch_transfer:
                    return session, original, None, None
                if concurrency:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        dispatches = list(pool.map(
                            lambda _: client.post(f"{base}/sessions/{session['id']}/transfer-check", json={"force_fresh": True}),
                            range(2),
                        ))
                    for response in dispatches:
                        payload = response.json()
                        trace.setdefault(label, []).append({
                            "method": "POST", "path": f"/sessions/{session['id']}/transfer-check",
                            "request": {"force_fresh": True}, "status": response.status_code,
                            "request_id": response.headers.get("X-Request-ID"), "response": payload,
                        })
                        if response.status_code != 200:
                            raise AssertionError(payload)
                    if dispatches[0].json()["question"]["id"] != dispatches[1].json()["question"]["id"]:
                        raise AssertionError("Concurrent transfer dispatches returned different questions")
                    transfer_dispatch = dispatches[0].json()
                else:
                    transfer_dispatch = request(label, "POST", f"/sessions/{session['id']}/transfer-check",
                                                {"force_fresh": True})
                assigned = request(label, "GET", f"/sessions/{session['id']}")["current_question"]
                if assigned["question_role"] != "transfer_check" or assigned["group_version_id"] == initial["group_version_id"]:
                    raise AssertionError("Transfer task is not a new pinned Matching Headings group")
                return session, original, assigned, transfer_dispatch

            def read_review(label: str, transfer_result: dict, learner: str):
                pending = request(label, "GET", "/reviews", params={"learner_id": learner, "status": "pending"})
                matches = [item for item in pending if item["trigger_attempt_id"] == transfer_result["attempt_id"]]
                if len(matches) != 1:
                    raise AssertionError("Expected one ReviewItem linked to the passing transfer Attempt")
                return matches[0]

            def complete_due_review(label: str, item: dict, learner: str, *, passed: bool):
                early_start = request(label, "POST", f"/reviews/{item['id']}/start",
                                      params={"learner_id": learner}, expected=400)
                early_complete = request(label, "POST", f"/reviews/{item['id']}/complete",
                                         {"review_notes": "cannot acknowledge before due"}, expected=400)
                clock.advance(days=1)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    starts = list(pool.map(lambda _: client.post(
                        f"{base}/reviews/{item['id']}/start", params={"learner_id": learner}), range(2)))
                if not all(response.status_code == 200 for response in starts):
                    raise AssertionError([response.text for response in starts])
                start_bodies = [response.json() for response in starts]
                for body in start_bodies:
                    trace.setdefault(label, []).append({
                        "method": "POST", "path": f"/reviews/{item['id']}/start",
                        "request": None, "query": {"learner_id": learner}, "status": 200,
                        "request_id": None, "response": body,
                    })
                if start_bodies[0]["review_session_id"] != start_bodies[1]["review_session_id"]:
                    raise AssertionError("Concurrent review starts created different sessions")
                review_session = request(label, "GET", f"/sessions/{start_bodies[0]['review_session_id']}")
                question = review_session["current_question"]
                if question["question_role"] != "review" or question["group_version_id"] != item["group_version_id"]:
                    raise AssertionError("Review did not restore its pinned group version")
                answers = private_answers(question)
                if not passed:
                    answers["item-1"], answers["item-2"] = answers["item-2"], answers["item-1"]
                review_payload = {
                    "question_id": question["id"], "group_version_id": question["group_version_id"],
                    "structured_answer": answers, "idempotency_key": learner + "-review",
                }
                with ThreadPoolExecutor(max_workers=2) as pool:
                    submissions = list(pool.map(
                        lambda _: client.post(f"{base}/sessions/{review_session['id']}/attempts", json=review_payload),
                        range(2),
                    ))
                for response in submissions:
                    payload = response.json()
                    trace.setdefault(label, []).append({
                        "method": "POST", "path": f"/sessions/{review_session['id']}/attempts",
                        "request": review_payload, "status": response.status_code,
                        "request_id": response.headers.get("X-Request-ID"), "response": payload,
                    })
                    if response.status_code != 201:
                        raise AssertionError(payload)
                if submissions[0].json()["attempt_id"] != submissions[1].json()["attempt_id"]:
                    raise AssertionError("Concurrent review submissions created different Attempts")
                result = submissions[0].json()
                replay = submit(label, review_session["id"], question, answers, learner + "-review")
                if result["attempt_id"] != replay["attempt_id"]:
                    raise AssertionError("Review retry did not replay its original Attempt")
                item_after = request(label, "GET", f"/reviews/{item['id']}", params={"learner_id": learner})
                if item_after["retention_verified"] is not passed:
                    raise AssertionError("ReviewItem retention flag did not match the delayed answer")
                return result, item_after

            # A: Academic/main-idea transfer and due review both pass; includes concurrent dispatch/start.
            session, initial, transfer, _ = reach_transfer("A_academic_main_success", "academic", "main_idea_vs_detail", "p4-a-main", concurrency=True)
            a_transfer_version = transfer["group_version_id"]
            a_transfer_newer_version = publish_new_group_revision(transfer)
            restored_a = request("A_academic_main_success", "GET", f"/sessions/{session['id']}")["current_question"]
            if restored_a["group_version_id"] != transfer["group_version_id"]:
                raise AssertionError("A transfer assignment changed after a newer group revision was published")
            transfer_answer = private_answers(transfer)
            transfer_result = submit("A_academic_main_success", session["id"], transfer, transfer_answer, "p4-a-transfer")
            transfer_replay = submit("A_academic_main_success", session["id"], transfer, transfer_answer, "p4-a-transfer")
            assert transfer_result["attempt_id"] == transfer_replay["attempt_id"]
            review = read_review("A_academic_main_success", transfer_result, "p4-a-main")
            a_review_version = review["group_version_id"]
            a_review_newer_version = publish_new_group_revision({"id": review["question_id"], "group_version_id": review["group_version_id"]})
            review_result, review_done = complete_due_review("A_academic_main_success", review, "p4-a-main", passed=True)

            # B: Academic/keyword transfer fails; state remains needs_practice and no retention record appears.
            session, _initial, transfer, _ = reach_transfer("B_academic_keyword_transfer_failure", "academic", "surface_keyword_matching", "p4-b-keyword")
            answers = private_answers(transfer)
            answers["item-1"], answers["item-2"] = answers["item-2"], answers["item-1"]
            transfer_failure = submit("B_academic_keyword_transfer_failure", session["id"], transfer, answers, "p4-b-transfer")
            if transfer_failure["next_action"] != "matching_headings_transfer_failed_needs_practice":
                raise AssertionError("Failed transfer was incorrectly accepted")

            # C: GT/main-idea transfer passes but its independent delayed review fails.
            session, _initial, transfer, _ = reach_transfer("C_gt_main_review_failure", "general_training", "main_idea_vs_detail", "p4-c-main")
            c_transfer_result = submit("C_gt_main_review_failure", session["id"], transfer, private_answers(transfer), "p4-c-transfer")
            review = read_review("C_gt_main_review_failure", c_transfer_result, "p4-c-main")
            c_review_result, c_review_failed = complete_due_review("C_gt_main_review_failure", review, "p4-c-main", passed=False)

            # D: GT/keyword transfer and delayed review both pass.
            session, _initial, transfer, _ = reach_transfer("D_gt_keyword_success", "general_training", "surface_keyword_matching", "p4-d-keyword")
            d_transfer_result = submit("D_gt_keyword_success", session["id"], transfer, private_answers(transfer), "p4-d-transfer")
            review = read_review("D_gt_keyword_success", d_transfer_result, "p4-d-keyword")
            d_review_result, d_review_done = complete_due_review("D_gt_keyword_success", review, "p4-d-keyword", passed=True)

            # Complete both remaining variant/cause combinations through delayed retention.
            session, _, transfer, _ = reach_transfer(
                "academic_keyword_full_success", "academic", "surface_keyword_matching", "p6-a-keyword")
            ak_transfer = submit("academic_keyword_full_success", session["id"], transfer, private_answers(transfer), "p6-ak-transfer")
            ak_review = read_review("academic_keyword_full_success", ak_transfer, "p6-a-keyword")
            ak_review_result, ak_review_done = complete_due_review("academic_keyword_full_success", ak_review, "p6-a-keyword", passed=True)
            session, _, transfer, _ = reach_transfer(
                "gt_main_full_success", "general_training", "main_idea_vs_detail", "p6-gt-main")
            gm_transfer = submit("gt_main_full_success", session["id"], transfer, private_answers(transfer), "p6-gm-transfer")
            gm_review = read_review("gt_main_full_success", gm_transfer, "p6-gt-main")
            gm_review_result, gm_review_done = complete_due_review("gt_main_full_success", gm_review, "p6-gt-main", passed=True)

            # E: transfer content exhaustion is explicit and cannot promote state.
            session, _initial, _unused, _ = reach_transfer(
                "E_transfer_exhaustion", "academic", "main_idea_vs_detail", "p4-e-empty",
                dispatch_transfer=False,
            )
            with factory.begin() as db:
                candidates = db.scalars(select(Question).where(
                    Question.topic_id == ACADEMIC,
                    Question.question_role == QuestionRole.TRANSFER_CHECK.value,
                )).all()
                old_roles = {question.id: question.question_role for question in candidates}
                for question in candidates:
                    question.question_role = QuestionRole.INITIAL.value
            empty_transfer = request("E_transfer_exhaustion", "POST", f"/sessions/{session['id']}/transfer-check",
                                     {"force_fresh": True})
            with factory.begin() as db:
                for question_id, role in old_roles.items():
                    db.get(Question, question_id).question_role = role
            if not empty_transfer["degraded"] or empty_transfer["question"] is not None:
                raise AssertionError("Transfer exhaustion must be explicit and non-promoting")
            transfer_empty_evidence = {"session_id": session["id"], "degraded": empty_transfer["degraded"],
                                       "message": empty_transfer["message"]}

            # F: review question exhaustion leaves the due item pending and unverified.
            session, _initial, transfer, _ = reach_transfer("F_review_exhaustion", "general_training", "main_idea_vs_detail", "p4-f-empty")
            transfer_success = submit("F_review_exhaustion", session["id"], transfer, private_answers(transfer), "p4-f-transfer")
            review = read_review("F_review_exhaustion", transfer_success, "p4-f-empty")
            with factory.begin() as db:
                question = db.get(Question, review["question_id"])
                old_role = question.question_role
                question.question_role = QuestionRole.INITIAL.value
            clock.advance(days=1)
            exhausted = request("F_review_exhaustion", "POST", f"/reviews/{review['id']}/start",
                                params={"learner_id": "p4-f-empty"})
            if exhausted["status"] != "pending" or exhausted["retention_verified"]:
                raise AssertionError("Exhausted review catalog must remain pending and unverified")
            with factory.begin() as db:
                db.get(Question, review["question_id"]).question_role = old_role

            # G/H before-due start/acknowledgment rejection is captured in the success cases above.
            # K/L execute prior TFNG string-answer and Python flow through the same actual HTTP server.
            request("K_tfng_legacy", "PUT", "/profile/exam-preparation",
                    {"exam_variant": "academic"}, params={"learner_id": "p4-legacy-tfng"})
            legacy_tfng = request("K_tfng_legacy", "POST", "/sessions", {
                "topic_id": "ielts-tfng-acad-reading-english", "learner_id": "p4-legacy-tfng",
            }, expected=201)
            tfng_question = legacy_tfng["current_question"]
            tfng_result = request("K_tfng_legacy", "POST", f"/sessions/{legacy_tfng['id']}/attempts", {
                "question_id": tfng_question["id"], "submitted_answer": "FALSE",
                "idempotency_key": "p4-legacy-tfng-answer",
            }, expected=201)
            py_session = request("L_python_legacy", "POST", "/sessions", {
                "topic_id": "topic_py_var_assign", "learner_id": "p4-legacy-python",
            }, expected=201)
            py_result = request("L_python_legacy", "POST", f"/sessions/{py_session['id']}/attempts", {
                "question_id": py_session["current_question_id"], "submitted_answer": "20 25",
                "idempotency_key": "p4-legacy-python-answer",
            }, expected=201)

            with factory() as db:
                for learner in ("p4-a-main", "p4-b-keyword", "p4-c-main", "p4-d-keyword", "p4-f-empty", "p6-a-keyword", "p6-gt-main"):
                    states = db.scalars(select(KnowledgeState).where(KnowledgeState.learner_id == learner)).all()
                    reviews = db.scalars(select(ReviewItem).where(ReviewItem.learner_id == learner)).all()
                    database_snapshot.append({
                        "learner_id": learner,
                        "knowledge_states": [{"id": s.id, "topic_id": s.topic_id, "status": s.status,
                                              "last_transfer_attempt_id": s.last_transfer_attempt_id,
                                              "unresolved_error_codes": s.unresolved_error_codes} for s in states],
                        "reviews": [{"id": r.id, "trigger_attempt_id": r.trigger_attempt_id,
                                     "group_version_id": r.group_version_id, "question_id": r.question_id,
                                     "attempt_id": r.attempt_id, "retention_verified": r.retention_verified,
                                     "retention_eligible": r.retention_eligible, "status": r.status,
                                     "review_outcome": r.review_outcome} for r in reviews],
                    })
                # Resolve full path provenance only by IDs; do not serialize rule payloads or keys.
                for label, transfer_result in [
                    ("A_academic_main_success", transfer_result),
                ]:
                    attempt = db.get(Attempt, transfer_result["attempt_id"])
                    if attempt:
                        case = db.scalar(select(DiagnosticCase).where(DiagnosticCase.session_id == attempt.session_id))
                        database_snapshot.append({"trace": label, "transfer_attempt_id": attempt.id,
                                                  "diagnostic_case_id": case.id if case else None,
                                                  "evidence_link_ids": [e.id for e in db.scalars(select(EvidenceLink).where(EvidenceLink.attempt_id == attempt.id))]})

            evidence = {
                "server": "Uvicorn + HTTPX over loopback TCP",
                "database": "temporary SQLite upgraded to Alembic head; deleted when script exits",
                "clock": {"initial": "2026-04-01T12:00:00Z", "advanced_by_client_without_system_clock_change": True},
                "execution_mode": "rules; FakeModelProvider configured; remote model calls disabled",
                "scenarios": {
                    "A": {"transfer_attempt_id": transfer_result["attempt_id"], "review_attempt_id": review_result["attempt_id"], "retention_verified": review_done["retention_verified"]},
                    "B": {"transfer_attempt_id": transfer_failure["attempt_id"], "next_action": transfer_failure["next_action"]},
                    "C": {"transfer_attempt_id": c_transfer_result["attempt_id"], "review_attempt_id": c_review_result["attempt_id"], "retention_verified": c_review_failed["retention_verified"]},
                    "D": {"transfer_attempt_id": d_transfer_result["attempt_id"], "review_attempt_id": d_review_result["attempt_id"], "retention_verified": d_review_done["retention_verified"]},
                    "academic_keyword_full_success": {"transfer_attempt_id": ak_transfer["attempt_id"], "review_attempt_id": ak_review_result["attempt_id"], "retention_verified": ak_review_done["retention_verified"]},
                    "gt_main_full_success": {"transfer_attempt_id": gm_transfer["attempt_id"], "review_attempt_id": gm_review_result["attempt_id"], "retention_verified": gm_review_done["retention_verified"]},
                    "E": transfer_empty_evidence,
                    "F": {"review_id": review["id"], "status": exhausted["status"], "retention_verified": exhausted["retention_verified"]},
                    "G_H": "premature review start and acknowledgment rejected with HTTP 400 (captured under A and C)",
                    "K": {"session_id": legacy_tfng["id"], "attempt_id": tfng_result["attempt_id"], "next_action": tfng_result["next_action"]},
                    "L": {"session_id": py_session["id"], "attempt_id": py_result["attempt_id"], "next_action": py_result["next_action"]},
                    "idempotency_and_concurrency": "parallel dispatch, parallel review-start, and same-key review replay verified in this HTTP run",
                },
                "database_evidence": database_snapshot,
                "version_updates": {"A_transfer_catalog_revision": a_transfer_newer_version,
                                    "A_review_catalog_revision": a_review_newer_version,
                                    "pinned_transfer_version": a_transfer_version,
                                    "pinned_review_version": a_review_version},
                "requests": trace,
                "private_answer_material_exposed_by_api": False,
            }
            target = output_path or BACKEND_DIR.parent / "docs/development/ielts-2b1-phase4-api-evidence/http-and-sqlite.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            client.close()
            return {"evidence_path": str(target), "scenario_results": evidence["scenarios"],
                    "requests": sum(len(calls) for calls in trace.values())}
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            clear_engine_cache()
            engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run_acceptance(args.output), ensure_ascii=False, indent=2))
