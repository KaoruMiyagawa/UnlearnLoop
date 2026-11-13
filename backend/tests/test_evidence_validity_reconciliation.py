"""Phase 6.1 evidence validity and state correction regressions."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.application.evidence_validity import apply_reconciliation, build_reconciliation_plan, evidence_status
from app.application.learning_service import LearningAppService
from app.application.diagnostic_service import DiagnosticAppService
from app.config import Settings
from app.domain.enums import EvidenceValidityStatus, KnowledgeMasteryStatus
from app.persistence.models import (
    Attempt, DecisionEvent, DiagnosticCase, EvidenceLink, EvidenceValidityEvent, Hypothesis,
    KnowledgeState, KnowledgeTopic, LearningSession, Question, ReadingGroupVersion,
    ReadingRuleVersion, ReviewItem,
)
from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database
from app.persistence.reading_groups import import_matching_headings
from app.model_provider import FakeModelProvider


def _display(group_id: str, version: str) -> dict:
    return {
        "id": group_id, "section_id": "section", "display_schema_version": "1",
        "passage": {"id": f"{group_id}-passage-{version}", "content_version": version,
                    "title": f"Passage {version}", "paragraphs": [
                        {"id": "paragraph-a", "text": f"Original independent passage {version}."},
                    ]},
        "options": [{"id": "i", "text": "A supported summary"}, {"id": "ii", "text": "A distractor"}],
        "items": [{"id": "item-a", "paragraph_id": "paragraph-a"}],
    }


def _rules(version: str) -> dict:
    return {"rules_version": version, "answers": {"item-a": "i"},
            "explanations": {"item-a": "The whole paragraph supports this summary."}}


def _attempt(db, *, topic, question, group, role: str, correct: bool, session_id: str) -> Attempt:
    session = LearningSession(id=session_id, learner_id="learner-validity", topic_id=topic.id,
        current_question_id=question.id, exam_variant="academic", status="completed")
    db.add(session)
    db.flush()
    rule = db.get(ReadingRuleVersion, group.rule_version_id)
    attempt = Attempt(
        id=f"attempt-{session_id}", session_id=session.id, question_id=question.id,
        question_version=1, question_snapshot_json={"question_type": "matching_headings"},
        attempt_role=role, submitted_answer="", group_version_id=group.id,
        structured_answer_json={"item-a": "i" if correct else "ii"},
        group_snapshot_json=group.display_json,
        item_evaluation_json={"correct_by_item": {"item-a": correct}, "correct_count": int(correct),
            "total_count": 1, "outcome": "correct" if correct else "incorrect",
            "group_version_id": group.id, "content_version": group.content_version,
            "display_schema_version": group.display_schema_version,
            "evaluation_rule_version": rule.rules_version, "rule_version_id": rule.id,
            "evaluation_source": "rule_check"},
        evaluation_rule_version=rule.rules_version,
        is_correct=correct, evaluation_status="evaluated", evaluation_summary="historical evaluation",
        submitted_at=datetime.now(timezone.utc), idempotency_key=f"idem-{session_id}",
    )
    db.add(attempt)
    db.flush()
    return attempt


@pytest.fixture
def validity_fixture(session_factory, monkeypatch, tmp_path):
    """Create v1 contaminated evidence plus v2 replacement in isolated SQLite."""
    registry_path = tmp_path / "registry.json"
    monkeypatch.setattr("app.application.evidence_validity.REGISTRY_PATH", registry_path)
    with session_factory() as db:
        topic = KnowledgeTopic(id="topic-validity", slug="topic-validity", domain_code="ielts_academic",
            title="Academic Reading", summary="fixture", difficulty_level=1, common_error_patterns=[])
        db.add(topic)
        db.flush()
        group_v1 = import_matching_headings(db, display=_display("audit-group", "1"), private_rules=_rules("1"),
            exam_variant="academic", provenance={"source": "isolated test", "license": "original"})
        group_v2 = import_matching_headings(db, display=_display("audit-group", "2"), private_rules=_rules("2"),
            exam_variant="academic", provenance={"source": "corrected isolated test", "license": "original"})
        question_v1 = Question(id="question-v1", topic_id=topic.id, question_role="transfer_check",
            question_type="matching_headings", prompt_text="Match headings", standard_answer="",
            answer_explanation="", evaluation_rubric={}, difficulty=1, version=1,
            reading_group_version_id=group_v1.id)
        question_v2 = Question(id="question-v2", topic_id=topic.id, question_role="transfer_check",
            question_type="matching_headings", prompt_text="Match headings", standard_answer="",
            answer_explanation="", evaluation_rubric={}, difficulty=1, version=1,
            reading_group_version_id=group_v2.id)
        db.add_all([question_v1, question_v2])
        db.flush()
        transfer = _attempt(db, topic=topic, question=question_v1, group=group_v1,
            role="transfer_check", correct=True, session_id="session-v1-transfer")
        review = _attempt(db, topic=topic, question=question_v1, group=group_v1,
            role="review", correct=True, session_id="session-v1-review")
        state_event = DecisionEvent(id="event-before", session_id=transfer.session_id,
            event_type="transfer_verified", to_state="transfer_verified", action="verify_transfer",
            reason="Historical v1 transfer was previously accepted.", payload_json={"attempt_id": transfer.id},
            idempotency_key="event-before")
        db.add(state_event)
        db.flush()
        case = DiagnosticCase(id="case-validity", session_id=transfer.session_id,
            trigger_attempt_id=transfer.id, topic_id=topic.id, status="resolved")
        db.add(case)
        db.flush()
        hypothesis = Hypothesis(id="hyp-validity", diagnostic_case_id=case.id,
            error_code="main_idea_vs_detail", name="Main idea versus detail",
            description="Candidate diagnosis", confidence=0.6, status="supported")
        db.add(hypothesis)
        db.flush()
        evidence_link = EvidenceLink(id="evidence-validity", hypothesis_id=hypothesis.id,
            attempt_id=transfer.id, decision_event_id=state_event.id, source_type="transfer_attempt",
            source_ref=f"attempt:{transfer.id}", relation="supports",
            summary="Historical transfer evidence.", reliability_note="Historically recorded.")
        db.add(evidence_link)
        state = KnowledgeState(id="state-validity", learner_id="learner-validity", topic_id=topic.id,
            status=KnowledgeMasteryStatus.TRANSFER_VERIFIED.value, unresolved_error_codes=[],
            last_decision_event_id=state_event.id, last_transfer_attempt_id=transfer.id,
            transition_reason="Historical transfer passed.")
        db.add(state)
        # ReviewItem has a FK to KnowledgeState; flush it explicitly before adding
        # the dependent row rather than relying on incidental unit-of-work ordering.
        db.flush()
        review_item = ReviewItem(id="review-v1", learner_id="learner-validity", topic_id=topic.id,
            session_id=transfer.session_id, trigger_reason="delayed retention check", status="completed",
            scheduled_for=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
            review_outcome="passed", schedule_key="review-v1", review_session_id=review.session_id,
            question_id=question_v1.id, attempt_id=review.id, trigger_attempt_id=transfer.id,
            group_version_id=group_v1.id, decision_event_id=state_event.id, knowledge_state_id=state.id,
            retention_verified=True, retention_eligible=True)
        db.add(review_item)
        db.commit()

        entries = []
        for version, rules, status, reason, replacement in [
            ("1", "1", "invalidated", "Reviewed v1 answer key is materially misleading.", "2"),
            ("2", "2", "eligible", "Corrected independent replacement; eligible for future normal submissions.", None),
        ]:
            entries.append({"group_id": "audit-group", "content_version": version, "rules_version": rules,
                "status": status, "reason": reason, "replacement_content_version": replacement})
        registry_path.write_text(json.dumps({"registry_version": "test-1", "source": "isolated fixture", "entries": entries}), encoding="utf-8")
        return {"topic_id": topic.id, "group_v1": group_v1.id, "group_v2": group_v2.id,
                "transfer_id": transfer.id, "review_attempt_id": review.id, "review_id": review_item.id,
                "state_id": state.id, "state_event_id": state_event.id,
                "evidence_link_id": evidence_link.id, "case_id": case.id}


def test_reconciliation_invalidates_v1_and_corrects_current_state_without_rewriting_history(
    session_factory, validity_fixture,
):
    refs = validity_fixture
    with session_factory() as db:
        attempt_before = db.get(Attempt, refs["transfer_id"])
        review_before = db.get(ReviewItem, refs["review_id"])
        assert attempt_before.is_correct is True
        assert review_before.retention_verified is True
        assert db.get(KnowledgeState, refs["state_id"]).status == "transfer_verified"

        plan = build_reconciliation_plan(db)
        assert plan["counts"]["attempts_invalidated"] == 2
        assert plan["counts"]["review_items_invalidated"] == 1
        result = apply_reconciliation(db, plan)
        db.commit()
        assert result["knowledge_state_changes"][0]["after"] == "insufficient_evidence"

        db.expire_all()
        assert db.get(Attempt, refs["transfer_id"]).is_correct is True  # immutable historical score
        assert db.get(ReviewItem, refs["review_id"]).retention_verified is True  # historical row is not rewritten
        assert db.get(KnowledgeState, refs["state_id"]).status == "insufficient_evidence"
        assert db.get(KnowledgeState, refs["state_id"]).last_transfer_attempt_id == refs["transfer_id"]
        assert evidence_status(db, "attempt", refs["transfer_id"]) == "invalidated"
        assert evidence_status(db, "review_item", refs["review_id"]) == "invalidated"
        assert evidence_status(db, "reading_group_version", refs["group_v2"]) == "eligible"
        assert db.scalar(select(func.count()).select_from(EvidenceValidityEvent)) == 7
        attempt_event = db.scalar(select(EvidenceValidityEvent).where(
            EvidenceValidityEvent.target_type == "attempt",
            EvidenceValidityEvent.target_id == refs["transfer_id"]))
        assert attempt_event.affected_refs_json["decision_event_ids"] == [refs["state_event_id"]]
        review_event = db.scalar(select(EvidenceValidityEvent).where(
            EvidenceValidityEvent.target_type == "review_item",
            EvidenceValidityEvent.target_id == refs["review_id"]))
        assert review_event.affected_refs_json["attempt_id"] == refs["review_attempt_id"]
        link_event = db.scalar(select(EvidenceValidityEvent).where(
            EvidenceValidityEvent.target_type == "evidence_link",
            EvidenceValidityEvent.target_id == refs["evidence_link_id"]))
        assert link_event.affected_refs_json["attempt_id"] == refs["transfer_id"]
        assert evidence_status(db, "evidence_link", refs["evidence_link_id"]) == "invalidated"
        service = DiagnosticAppService(db, model_provider=FakeModelProvider(), settings=Settings(APP_ENV="testing"))
        public_evidence = service.get_evidence_for_case(refs["case_id"])
        assert public_evidence[0].evidence_validity_status == EvidenceValidityStatus.INVALIDATED

        # A second apply is idempotent and cannot multiply validity or decision events.
        second_plan = build_reconciliation_plan(db)
        apply_reconciliation(db, second_plan)
        db.commit()
        assert db.scalar(select(func.count()).select_from(EvidenceValidityEvent)) == 7
        assert db.scalar(select(func.count()).select_from(DecisionEvent).where(
            DecisionEvent.event_type == "evidence_validity_reconciled")) == 1
        target_event = db.scalar(select(EvidenceValidityEvent).where(
            EvidenceValidityEvent.target_type == "attempt",
            EvidenceValidityEvent.target_id == refs["transfer_id"]))
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE evidence_validity_events SET reason='tampered' WHERE id=:id"),
                       {"id": target_event.id})
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(text("DELETE FROM evidence_validity_events WHERE id=:id"),
                       {"id": target_event.id})
        db.rollback()


def test_effective_profile_and_history_hide_invalid_claims_but_keep_historical_results(session_factory, validity_fixture):
    refs = validity_fixture
    with session_factory() as db:
        apply_reconciliation(db)
        db.commit()
        service = LearningAppService(db)
        states = service.list_knowledge_states("learner-validity")
        state = next(item for item in states if item.id == refs["state_id"])
        assert state.status == "insufficient_evidence"
        assert state.evidence_validity_status == EvidenceValidityStatus.INVALIDATED
        history = service.list_learning_history("learner-validity")
        old_transfer = next(item for item in history if item.id == f"attempt:{refs['transfer_id']}")
        assert old_transfer.evidence_validity_status == EvidenceValidityStatus.INVALIDATED
        assert "不作为能力证据" in old_transfer.summary
        reconciled = next(item for item in history if item.kind == "evidence_reconciled")
        assert reconciled.evidence_validity_status == EvidenceValidityStatus.INVALIDATED
        review = service.get_review(refs["review_id"], "learner-validity")
        assert review.evidence_validity_status == EvidenceValidityStatus.INVALIDATED
        assert review.retention_verified is False


def test_unknown_matching_provenance_is_review_required_not_invalidated(session_factory, validity_fixture):
    refs = validity_fixture
    with session_factory() as db:
        question = db.get(Question, "question-v1")
        # A historical matching transfer with no immutable group reference is not
        # guessed by date or ID; the planner will require provenance review.
        unknown = Attempt(id="attempt-unknown", session_id="session-v1-transfer", question_id=question.id,
            question_version=1, question_snapshot_json={"question_type": "matching_headings"},
            attempt_role="transfer_check", submitted_answer="legacy", is_correct=True,
            evaluation_status="evaluated", evaluation_summary="old", submitted_at=datetime.now(timezone.utc),
            idempotency_key="unknown-provenance")
        db.add(unknown)
        db.commit()
        plan = build_reconciliation_plan(db)
        assert unknown.id in plan["attempts_review_required"]
        apply_reconciliation(db, plan)
        db.commit()
        assert evidence_status(db, "attempt", unknown.id) == "review_required"


def test_new_submission_on_invalidated_version_is_rejected_without_attempt_or_state_change(client, session_factory, validity_fixture):
    refs = validity_fixture
    with session_factory() as db:
        apply_reconciliation(db)
        topic = db.get(KnowledgeTopic, refs["topic_id"])
        db.add(LearningSession(id="session-invalid-v1-new", learner_id="learner-validity",
            topic_id=topic.id, current_question_id="question-v1", exam_variant="academic",
            status="transfer_checking"))
        db.commit()
        before_attempts = db.scalar(select(func.count()).select_from(Attempt))
        before_state = db.get(KnowledgeState, refs["state_id"]).status
    response = client.post("/api/v1/sessions/session-invalid-v1-new/attempts", json={
        "question_id": "question-v1", "group_version_id": refs["group_v1"],
        "structured_answer": {"item-a": "i"}, "idempotency_key": "invalid-v1-submit"})
    assert response.status_code == 400
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == before_attempts
        assert db.get(KnowledgeState, refs["state_id"]).status == before_state


def test_eligible_independent_v2_attempt_preserves_matching_mastery(session_factory, validity_fixture):
    refs = validity_fixture
    with session_factory() as db:
        original = db.get(Attempt, refs["transfer_id"])
        old_session = db.get(LearningSession, original.session_id)
        v2_question = db.get(Question, "question-v2")
        v2_attempt = _attempt(db, topic=old_session.topic, question=v2_question,
            group=db.get(ReadingGroupVersion, refs["group_v2"]), role="transfer_check", correct=True,
            session_id="session-v2-transfer")
        # New eligible evidence is independent from the invalid v1 attempt.
        db.flush()
        apply_reconciliation(db)
        db.commit()
        db.expire_all()
        state = db.get(KnowledgeState, refs["state_id"])
        assert state.status == "transfer_verified"
        assert state.last_transfer_attempt_id == v2_attempt.id
        assert evidence_status(db, "attempt", v2_attempt.id) == "eligible"


def test_revalidation_route_requires_invalidated_state_and_uses_eligible_current_group(test_settings, session_factory, validity_fixture):
    refs = validity_fixture
    from app.api.v1.dependencies import get_session_factory
    from app.config import get_settings
    from app.main import create_app
    from app.persistence.models import ExamPreparationProfile

    with session_factory() as db:
        apply_reconciliation(db)
        db.add(ExamPreparationProfile(learner_id="learner-validity", exam_variant="academic",
            goal_type="band", target_overall_band=8.0, actual_level_status="not_assessed", spec_version="test"))
        # Revalidation uses an ordinary current Reading question referencing the
        # corrected v2 group; it does not grant mastery itself.
        question = db.get(Question, "question-v2")
        question.question_role = "initial"
        db.commit()
    app = create_app(test_settings)
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_settings] = lambda: test_settings
    with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as http:
        response = http.post("/api/v1/profile/evidence-revalidation", json={
            "topic_id": refs["topic_id"], "learner_id": "learner-validity", "exam_variant": "academic",
            "idempotency_key": "phase6-1-revalidate-1"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["available"] is True
        assert payload["session"]["current_question"]["group_version_id"] == refs["group_v2"]
        assert payload["session"]["current_question"]["question_type"] == "matching_headings"


def test_0004_to_0007_keeps_legacy_python_and_tfng_history(tmp_path):
    from tests.conftest import seed_historical_question

    db_path = tmp_path / "phase6-1-migration.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_db_engine(database_url=url)
    try:
        upgrade_database(database_url=url, engine=engine, revision="0004_ielts_exam_profiles")
        for domain in ("python", "tfng"):
            seed_historical_question(engine, f"topic-{domain}", f"legacy-{domain}", f"question-{domain}")
            with engine.begin() as conn:
                if domain == "tfng":
                    conn.execute(text(
                        "UPDATE knowledge_topics SET domain_code='ielts_academic' WHERE id='topic-tfng'"))
                    conn.execute(text(
                        "UPDATE questions SET question_type='short_text' WHERE id='question-tfng'"))
                conn.execute(text("""INSERT INTO learning_sessions
                    (id, learner_id, topic_id, current_question_id, status, started_at, updated_at)
                    VALUES (:id,'legacy-learner',:topic,:question,'active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""),
                    {"id": f"session-{domain}", "topic": f"topic-{domain}", "question": f"question-{domain}"})
                if domain == "tfng":
                    conn.execute(text(
                        "UPDATE learning_sessions SET exam_variant='academic' WHERE id='session-tfng'"))
                conn.execute(text("""INSERT INTO attempts
                    (id,session_id,question_id,question_version,question_snapshot_json,attempt_role,submitted_answer,
                     is_correct,evaluation_status,submitted_at)
                    VALUES (:id,:session,:question,1,'{}','initial','kept-answer',0,'evaluated',CURRENT_TIMESTAMP)"""),
                    {"id": f"attempt-{domain}", "session": f"session-{domain}", "question": f"question-{domain}"})
        upgrade_database(database_url=url, engine=engine)
        with create_session_factory(engine)() as db:
            for domain in ("python", "tfng"):
                attempt = db.get(Attempt, f"attempt-{domain}")
                assert attempt.submitted_answer == "kept-answer"
                assert attempt.is_correct is False
                assert attempt.group_version_id is None
                assert db.get(LearningSession, f"session-{domain}").current_group_version_id is None
    finally:
        engine.dispose()
