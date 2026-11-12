"""Run Phase 6.1 reconciliation through an isolated SQLite DB and real Uvicorn HTTP."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
from sqlalchemy import func, select

from app.application.evidence_validity import build_reconciliation_plan
from app.application.evidence_validity import evidence_status
from app.config import Settings
from app.domain.enums import KnowledgeMasteryStatus
from app.main import create_app
from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database
from app.persistence.models import (
    Attempt, DecisionEvent, DiagnosticCase, EvidenceLink, EvidenceValidityEvent, ExamPreparationProfile,
    Hypothesis, KnowledgeState, KnowledgeTopic, LearningSession, Question, ReadingGroupVersion, ReviewItem,
)
from app.persistence.reading_groups import import_matching_headings


def group_content(version: str) -> dict:
    return {
        "id": "ielts-mh-academic-main-transfer-group", "section_id": "academic-reading",
        "display_schema_version": "1", "allow_reuse": False,
        "passage": {"id": f"phase6-1-riverside-{version}", "content_version": version,
                    "title": f"Riverside fieldwork v{version}", "paragraphs": [
                        {"id": "paragraph-a", "text": f"In version {version}, the team compared monitoring methods across five river sites."},
                    ]},
        "options": [{"id": "i", "text": "A comparison of monitoring methods"},
                    {"id": "ii", "text": "A detail about one instrument"}],
        "items": [{"id": "item-a", "paragraph_id": "paragraph-a"}],
    }


def private_rules(version: str) -> dict:
    return {"rules_version": version, "answers": {"item-a": "i"},
            "explanations": {"item-a": "The full paragraph compares methods across sites."}}


def evaluation_record(group: ReadingGroupVersion, rule_id: str, *, correct: bool) -> dict:
    return {"correct_by_item": {"item-a": correct}, "correct_count": int(correct),
            "total_count": 1, "outcome": "correct" if correct else "incorrect",
            "group_version_id": group.id, "content_version": group.content_version,
            "display_schema_version": group.display_schema_version,
            "evaluation_rule_version": "1" if group.content_version == "1" else "2",
            "rule_version_id": rule_id, "evaluation_source": "rule_check"}


def snapshot(db, learner_id: str, ids: dict) -> dict:
    state = db.get(KnowledgeState, ids["state"])
    mixed_state = db.get(KnowledgeState, ids["mixed_state"])
    review = db.get(ReviewItem, ids["review"])
    transfer = db.get(Attempt, ids["transfer"])
    review_attempt = db.get(Attempt, ids["review_attempt"])
    return {
        "knowledge_state": {"status": state.status, "last_transfer_attempt_id": state.last_transfer_attempt_id,
                            "transition_reason": state.transition_reason},
        "mixed_v1_v2_knowledge_state": {
            "status": mixed_state.status,
            "last_transfer_attempt_id": mixed_state.last_transfer_attempt_id,
            "v1_attempt_validity": evidence_status(db, "attempt", ids["mixed_v1_attempt"]),
            "v2_attempt_validity": evidence_status(db, "attempt", ids["mixed_v2_attempt"]),
        },
        "historical_transfer_attempt": {"id": transfer.id, "is_correct": transfer.is_correct,
                                        "group_version_id": transfer.group_version_id,
                                        "evaluation_rule_version": transfer.evaluation_rule_version},
        "historical_review_attempt": {"id": review_attempt.id, "is_correct": review_attempt.is_correct,
                                      "group_version_id": review_attempt.group_version_id},
        "review_item": {"id": review.id, "status": review.status,
                        "historical_retention_verified_field": review.retention_verified,
                        "review_outcome": review.review_outcome},
        "evidence_link": {"id": ids["evidence_link"],
                          "historical_relation": db.get(EvidenceLink, ids["evidence_link"]).relation,
                          "current_validity": evidence_status(db, "evidence_link", ids["evidence_link"])},
        "validity_event_count": db.scalar(select(func.count()).select_from(EvidenceValidityEvent)),
        "reconciliation_event_count": db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.event_type == "evidence_validity_reconciled")),
    }


def build_fixture(database_path: Path, *, learner_id: str = "phase6-1-http-learner") -> tuple[Settings, object, dict]:
    url = f"sqlite:///{database_path.as_posix()}"
    settings = Settings(APP_NAME="VerbaTrail Phase 6.1 acceptance", APP_ENV="testing",
                        DATABASE_URL=url, MODEL_PROVIDER="fake", MODEL_API_KEY="",
                        ALLOW_REMOTE_MODEL_CALLS=False)
    engine = create_db_engine(database_url=url)
    upgrade_database(database_url=url, engine=engine)
    factory = create_session_factory(engine)
    ids = {"learner": learner_id, "topic": "ielts-mh-academic",
           "mixed_learner": f"{learner_id}-with-v2-evidence",
           "mixed_state": "phase6-1-mixed-knowledge-state",
           "mixed_v1_attempt": "phase6-1-mixed-v1-transfer-attempt",
           "mixed_v2_attempt": "phase6-1-mixed-v2-transfer-attempt",
           "group_v1": None, "group_v2": None, "transfer": "phase6-1-transfer-attempt",
           "review_attempt": "phase6-1-review-attempt", "review": "phase6-1-review-item",
           "state": "phase6-1-knowledge-state", "case": "phase6-1-diagnostic-case",
           "hypothesis": "phase6-1-hypothesis", "evidence_link": "phase6-1-evidence-link"}

    with factory() as db:
        topic = KnowledgeTopic(id=ids["topic"], slug="ielts-mh-academic", domain_code="ielts_academic",
            title="Matching Headings · Academic", summary="Isolated Phase 6.1 evidence fixture",
            difficulty_level=2, common_error_patterns=[])
        db.add(topic)
        db.flush()
        v1 = import_matching_headings(db, display=group_content("1"), private_rules=private_rules("1"),
            exam_variant="academic", provenance={"source": "Phase 6.1 isolated HTTP fixture", "license": "original test content"})
        v2 = import_matching_headings(db, display=group_content("2"), private_rules=private_rules("2"),
            exam_variant="academic", provenance={"source": "Phase 6.1 corrected fixture", "license": "original test content"})
        ids["group_v1"], ids["group_v2"] = v1.id, v2.id
        q_transfer = Question(id="phase6-1-q-transfer", topic_id=topic.id, question_role="transfer_check",
            question_type="matching_headings", prompt_text="Match each paragraph to its heading.",
            standard_answer="", answer_explanation="", evaluation_rubric={}, difficulty=2, version=1,
            reading_group_version_id=v1.id)
        q_review = Question(id="phase6-1-q-review", topic_id=topic.id, question_role="review",
            question_type="matching_headings", prompt_text="Match each paragraph to its heading.",
            standard_answer="", answer_explanation="", evaluation_rubric={}, difficulty=2, version=1,
            reading_group_version_id=v1.id)
        q_revalidation = Question(id="phase6-1-q-revalidation", topic_id=topic.id, question_role="initial",
            question_type="matching_headings", prompt_text="Match each paragraph to its heading.",
            standard_answer="", answer_explanation="", evaluation_rubric={}, difficulty=2, version=2,
            reading_group_version_id=v2.id)
        db.add_all([q_transfer, q_review, q_revalidation])
        db.flush()

        transfer_session = LearningSession(id="phase6-1-transfer-session", learner_id=ids["learner"],
            topic_id=topic.id, current_question_id=q_transfer.id, exam_variant="academic", status="completed")
        review_session = LearningSession(id="phase6-1-review-session", learner_id=ids["learner"],
            topic_id=topic.id, current_question_id=q_review.id, exam_variant="academic", status="completed")
        db.add_all([transfer_session, review_session])
        db.flush()
        transfer = Attempt(id=ids["transfer"], session_id=transfer_session.id, question_id=q_transfer.id,
            question_version=1, question_snapshot_json={"question_type": "matching_headings"},
            attempt_role="transfer_check", submitted_answer="", group_version_id=v1.id,
            structured_answer_json={"item-a": "i"}, group_snapshot_json=v1.display_json,
            item_evaluation_json=evaluation_record(v1, v1.rule_version_id, correct=True), evaluation_rule_version="1", is_correct=True,
            evaluation_status="evaluated", evaluation_summary="historically marked passed",
            idempotency_key="phase6-1-transfer-idempotency", submitted_at=datetime.now(timezone.utc))
        review_attempt = Attempt(id=ids["review_attempt"], session_id=review_session.id,
            question_id=q_review.id, question_version=1,
            question_snapshot_json={"question_type": "matching_headings"}, attempt_role="review",
            submitted_answer="", group_version_id=v1.id, structured_answer_json={"item-a": "i"},
            group_snapshot_json=v1.display_json, item_evaluation_json=evaluation_record(v1, v1.rule_version_id, correct=True),
            evaluation_rule_version="1", is_correct=True, evaluation_status="evaluated",
            evaluation_summary="historically marked retention passed",
            idempotency_key="phase6-1-review-idempotency", submitted_at=datetime.now(timezone.utc))
        db.add_all([transfer, review_attempt])
        db.flush()
        prior = DecisionEvent(id="phase6-1-prior-transfer-event", session_id=transfer_session.id,
            event_type="transfer_verified", to_state="transfer_verified", action="verify_transfer",
            reason="Historical v1 pass before validity audit.", payload_json={"attempt_id": transfer.id},
            idempotency_key="phase6-1-prior-event")
        db.add(prior)
        db.flush()
        case = DiagnosticCase(id=ids["case"], session_id=transfer_session.id,
            trigger_attempt_id=transfer.id, topic_id=topic.id, status="resolved")
        db.add(case)
        db.flush()
        hypothesis = Hypothesis(id=ids["hypothesis"], diagnostic_case_id=case.id,
            error_code="main_idea_vs_detail", name="Main idea versus detail",
            description="Historical candidate hypothesis", confidence=0.6, status="supported")
        db.add(hypothesis)
        db.flush()
        db.add(EvidenceLink(id=ids["evidence_link"], hypothesis_id=hypothesis.id,
            attempt_id=transfer.id, decision_event_id=prior.id, source_type="transfer_attempt",
            source_ref=f"attempt:{transfer.id}", relation="supports",
            summary="Historical transfer supported this candidate.", reliability_note="Previously recorded."))
        state = KnowledgeState(id=ids["state"], learner_id=ids["learner"], topic_id=topic.id,
            status=KnowledgeMasteryStatus.TRANSFER_VERIFIED.value, unresolved_error_codes=[],
            last_decision_event_id=prior.id, last_transfer_attempt_id=transfer.id,
            transition_reason="Historical v1 transfer passed.")
        db.add(state)
        # ReviewItem references KnowledgeState; persist its FK target explicitly
        # before adding the dependent review record.
        db.flush()
        db.add(ReviewItem(id=ids["review"], learner_id=ids["learner"], topic_id=topic.id,
            session_id=transfer_session.id, trigger_reason="delayed retention", status="completed",
            scheduled_for=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
            review_outcome="passed", schedule_key="phase6-1-review-schedule",
            review_session_id=review_session.id, question_id=q_review.id, attempt_id=review_attempt.id,
            trigger_attempt_id=transfer.id, group_version_id=v1.id, decision_event_id=prior.id,
            knowledge_state_id=state.id, retention_verified=True, retention_eligible=True))
        db.add(ExamPreparationProfile(learner_id=ids["learner"], exam_variant="academic", goal_type="band",
            target_overall_band=8.0, actual_level_status="not_assessed", spec_version="test-catalog"))

        # A second learner has both a contaminated v1 transfer and a separate,
        # eligible v2 transfer. Reconciliation must retain the current ability
        # claim and move its evidence pointer to the independent v2 Attempt.
        mixed_v1_session = LearningSession(id="phase6-1-mixed-v1-session", learner_id=ids["mixed_learner"],
            topic_id=topic.id, current_question_id=q_transfer.id, exam_variant="academic", status="completed")
        mixed_v2_session = LearningSession(id="phase6-1-mixed-v2-session", learner_id=ids["mixed_learner"],
            topic_id=topic.id, current_question_id=q_revalidation.id, exam_variant="academic", status="completed")
        db.add_all([mixed_v1_session, mixed_v2_session])
        db.flush()
        mixed_v1 = Attempt(id=ids["mixed_v1_attempt"], session_id=mixed_v1_session.id,
            question_id=q_transfer.id, question_version=1,
            question_snapshot_json={"question_type": "matching_headings"}, attempt_role="transfer_check",
            submitted_answer="", group_version_id=v1.id, structured_answer_json={"item-a": "i"},
            group_snapshot_json=v1.display_json, item_evaluation_json=evaluation_record(v1, v1.rule_version_id, correct=True),
            evaluation_rule_version="1", is_correct=True, evaluation_status="evaluated",
            evaluation_summary="historically passed on v1", idempotency_key="phase6-1-mixed-v1-idem",
            submitted_at=datetime.now(timezone.utc))
        mixed_v2 = Attempt(id=ids["mixed_v2_attempt"], session_id=mixed_v2_session.id,
            question_id=q_revalidation.id, question_version=2,
            question_snapshot_json={"question_type": "matching_headings"}, attempt_role="transfer_check",
            submitted_answer="", group_version_id=v2.id, structured_answer_json={"item-a": "i"},
            group_snapshot_json=v2.display_json, item_evaluation_json=evaluation_record(v2, v2.rule_version_id, correct=True),
            evaluation_rule_version="2", is_correct=True, evaluation_status="evaluated",
            evaluation_summary="independent v2 transfer passed", idempotency_key="phase6-1-mixed-v2-idem",
            submitted_at=datetime.now(timezone.utc))
        db.add_all([mixed_v1, mixed_v2])
        db.flush()
        mixed_decision = DecisionEvent(id="phase6-1-mixed-prior-event", session_id=mixed_v1_session.id,
            event_type="transfer_verified", to_state="transfer_verified", action="verify_transfer",
            reason="Previously verified before the content audit.", payload_json={"attempt_id": mixed_v1.id},
            idempotency_key="phase6-1-mixed-prior-idem")
        db.add(mixed_decision)
        db.flush()
        db.add(KnowledgeState(id=ids["mixed_state"], learner_id=ids["mixed_learner"], topic_id=topic.id,
            status=KnowledgeMasteryStatus.TRANSFER_VERIFIED.value, unresolved_error_codes=[],
            last_decision_event_id=mixed_decision.id, last_transfer_attempt_id=mixed_v1.id,
            transition_reason="v1 and v2 transfer history co-exist."))
        db.commit()
    return settings, (engine, factory), ids


def start_server(app, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if server.started:
            return server, thread
        if not thread.is_alive():
            raise RuntimeError("Uvicorn exited before becoming ready.")
        time.sleep(0.05)
    server.should_exit = True
    raise TimeoutError("Uvicorn did not start in time.")


def response_record(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status": response.status_code, "body": body}


def sqlite_integrity(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None, help="Evidence JSON destination")
    args = parser.parse_args()
    evidence_dir = args.output.parent if args.output else Path(__file__).resolve().parents[2] / "docs" / "development" / "ielts-2b1-phase6-1-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    output = args.output or evidence_dir / "real-http-reconciliation.json"

    with tempfile.TemporaryDirectory(prefix="verbatrail-phase6-1-") as temp:
        database = Path(temp) / "phase6-1-isolated.sqlite"
        settings, (engine, factory), ids = build_fixture(database)
        try:
            before_hash = __import__("hashlib").sha256(database.read_bytes()).hexdigest()
            with factory() as db:
                before = snapshot(db, ids["learner"], ids)
                dry_run = build_reconciliation_plan(db)
            cli = Path(__file__).with_name("reconcile_matching_headings_evidence.py")
            dry_run_cli = subprocess.run([sys.executable, str(cli), "--database-url", settings.database_url],
                capture_output=True, text=True, check=True)
            dry_run_hash = __import__("hashlib").sha256(database.read_bytes()).hexdigest()
            apply_command = [sys.executable, str(cli), "--database-url", settings.database_url,
                "--apply", "--confirm", "APPLY_PHASE6_1_TO_ISOLATED_SQLITE_ONLY"]
            with ThreadPoolExecutor(max_workers=2) as executor:
                concurrent_apply = list(executor.map(
                    lambda _: subprocess.run(apply_command, capture_output=True, text=True, check=True), range(2)))
            applied = json.loads(concurrent_apply[0].stdout)
            backup_path = Path(applied["backup"])
            backup_hash = __import__("hashlib").sha256(backup_path.read_bytes()).hexdigest()
            backup_integrity = sqlite_integrity(backup_path)
            current_integrity = sqlite_integrity(database)
            with factory() as db:
                db.expire_all()
                after = snapshot(db, ids["learner"], ids)
                repeated_plan = build_reconciliation_plan(db)
            repeat_cli = subprocess.run([sys.executable, str(cli), "--database-url", settings.database_url,
                "--apply", "--confirm", "APPLY_PHASE6_1_TO_ISOLATED_SQLITE_ONLY"],
                capture_output=True, text=True, check=True)
            repeat_result = json.loads(repeat_cli.stdout)
            with factory() as db:
                repeated = snapshot(db, ids["learner"], ids)
            after_hash = __import__("hashlib").sha256(database.read_bytes()).hexdigest()

            from app.api.v1.dependencies import get_session_factory
            from app.config import get_settings
            app = create_app(settings)
            app.dependency_overrides[get_settings] = lambda: settings
            app.dependency_overrides[get_session_factory] = lambda: factory
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server, thread = start_server(app, port)
            base = f"http://127.0.0.1:{port}"
            try:
                with httpx.Client(base_url=base, timeout=5.0, trust_env=False) as client:
                    health = client.get("/api/v1/health")
                    history = client.get("/api/v1/profile/history", params={"learner_id": ids["learner"]})
                    states = client.get("/api/v1/profile/knowledge-states", params={"learner_id": ids["learner"]})
                    mixed_states = client.get("/api/v1/profile/knowledge-states", params={"learner_id": ids["mixed_learner"]})
                    dashboard = client.get("/api/v1/profile/summary", params={"learner_id": ids["learner"]})
                    review = client.get(f"/api/v1/reviews/{ids['review']}", params={"learner_id": ids["learner"]})
                    evidence = client.get(f"/api/v1/diagnoses/{ids['case']}/evidence")
                    revalidation = client.post("/api/v1/profile/evidence-revalidation", json={
                        "topic_id": ids["topic"], "learner_id": ids["learner"],
                        "exam_variant": "academic", "idempotency_key": "phase6-1-http-revalidation"})
                    # Replaying the same request must return its original session.
                    replay = client.post("/api/v1/profile/evidence-revalidation", json={
                        "topic_id": ids["topic"], "learner_id": ids["learner"],
                        "exam_variant": "academic", "idempotency_key": "phase6-1-http-revalidation"})
                    payload = {"health": response_record(health), "history": response_record(history),
                        "knowledge_states": response_record(states), "revalidation": response_record(revalidation),
                        "mixed_version_knowledge_states": response_record(mixed_states),
                        "revalidation_replay": response_record(replay), "dashboard": response_record(dashboard),
                        "review": response_record(review), "diagnostic_evidence": response_record(evidence)}
            finally:
                server.should_exit = True
                thread.join(timeout=5)

            evidence = {"mode": "real_uvicorn_http", "database": str(database),
                "database_hash_before_reconciliation": before_hash,
                "database_hash_after_reconciliation": after_hash,
                "preapply_backup_sha256": backup_hash,
                "preapply_backup_hash_matches_cli": backup_hash == applied["backup_sha256"],
                "preapply_backup_integrity_check": backup_integrity,
                "postapply_database_integrity_check": current_integrity,
                "migrations": "fresh isolated SQLite upgraded to current Alembic head",
                "model_execution": "disabled; deterministic evidence reconciliation only",
                "record_ids": ids, "dry_run_plan": dry_run, "dry_run_cli_stdout": dry_run_cli.stdout,
                "dry_run_unchanged_database_hash": dry_run_hash == before_hash,
                "apply_result": applied,
                "concurrent_apply_results": [json.loads(item.stdout) for item in concurrent_apply],
                "before_database_state": before, "after_database_state": after,
                "after_idempotent_replay": repeated, "idempotent_replay_result": repeat_result,
                "http": payload}
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"evidence_file": str(output), "before": before["knowledge_state"],
                "after": after["knowledge_state"], "review_before": before["review_item"],
                "review_after": after["review_item"], "http_statuses": {key: val["status"] for key, val in payload.items()},
                "revalidation_session_id": (payload["revalidation"]["body"].get("session") or {}).get("id")
                    if isinstance(payload["revalidation"]["body"], dict) else None,
                "replay_session_id": (payload["revalidation_replay"]["body"].get("session") or {}).get("id")
                    if isinstance(payload["revalidation_replay"]["body"], dict) else None},
                ensure_ascii=False, indent=2))
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
