"""Comprehensive Stage 2 tests for domain models, migrations, content pack, and invariants."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR, Settings
from app.domain.enums import (
    AttemptEvaluationStatus,
    DiagnosticCaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    InterventionAction,
    KnowledgeMasteryStatus,
    QuestionRole,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.exceptions import (
    DomainRuleViolationError,
    ImmutableRecordError,
    InvalidStateTransitionError,
    UnverifiedMasteryError,
)
from app.persistence.database import transactional_session
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    EvidenceLink,
    Hypothesis,
    KnowledgeState,
    KnowledgeTopic,
    LearningMaterial,
    LearningSession,
    Question,
    ReviewItem,
)
from app.persistence.repositories import LearningRepository
from app.persistence.seed import (
    import_content_pack,
    load_content_pack_file,
    validate_python_snippet_syntax,
)


def test_alembic_migration_from_empty_database_and_sqlite_fk_pragma(
    migrated_engine: Engine,
) -> None:
    """1. Verify Alembic initializes all 13 tables (12 business + 1 alembic_version) and enables SQLite FKs."""
    inspector = inspect(migrated_engine)
    tables = set(inspector.get_table_names())

    expected_stage2_tables = {
        "knowledge_topics",
        "knowledge_topic_dependencies",
        "learning_materials",
        "questions",
        "learning_sessions",
        "attempts",
        "diagnostic_cases",
        "hypotheses",
        "decision_events",
        "evidence_links",
        "knowledge_states",
        "review_items",
    }
    assert len(expected_stage2_tables) == 12
    assert expected_stage2_tables.issubset(tables)
    assert "alembic_version" in tables

    with migrated_engine.connect() as conn:
        fk_enabled = conn.execute(text("PRAGMA foreign_keys")).scalar_one()
        assert fk_enabled == 1


def test_content_pack_import_idempotency_and_python3_syntax(
    session_factory: sessionmaker[Session],
) -> None:
    """8. Verify content pack imports cleanly, validates Python 3 syntax, and is idempotent."""
    raw_pack = load_content_pack_file()
    assert raw_pack["domain_code"] == "python"
    assert len(raw_pack["topics"]) == 5

    with transactional_session(session_factory) as session:
        first_run = import_content_pack(session)
        assert first_run.topics_created == 5
        assert first_run.topics_updated == 0
        assert first_run.dependencies_created == 6
        assert first_run.materials_created == 5
        assert first_run.questions_created == 22

    # Second import on the same database must update in place without duplicating rows
    with transactional_session(session_factory) as session:
        second_run = import_content_pack(session)
        assert second_run.topics_created == 0
        assert second_run.topics_updated == 5
        assert second_run.dependencies_created == 0
        assert second_run.materials_created == 0
        assert second_run.materials_updated == 5
        assert second_run.questions_created == 0
        assert second_run.questions_updated == 22

        repo = LearningRepository(session)
        topics = repo.list_topics(domain_code="python")
        assert len(topics) == 5

    # Invalid Python 3 syntax must be rejected by syntax validator
    with pytest.raises(DomainRuleViolationError, match="Invalid Python 3 syntax"):
        validate_python_snippet_syntax(
            "for (i = 0; i < 3; i++) total += i",
            context_id="bad_c_loop",
        )


def test_topic_dependencies_and_question_queries_by_role(
    session_factory: sessionmaker[Session],
) -> None:
    """3. Verify querying topics, prerequisite dependencies, materials, and questions by role."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)

        for_loop_topic = repo.get_topic_by_slug("py-for-loop")
        assert for_loop_topic is not None
        prereq_slugs = {t.slug for t in for_loop_topic.prerequisites}
        assert prereq_slugs == {"py-variable-assignment", "py-range-function"}
        assert len(for_loop_topic.materials) == 1
        assert len(for_loop_topic.common_error_patterns) >= 2

        initial_qs = repo.list_questions_for_topic(
            for_loop_topic.id, role=QuestionRole.INITIAL
        )
        followup_qs = repo.list_questions_for_topic(
            for_loop_topic.id, role=QuestionRole.DIAGNOSTIC_FOLLOWUP
        )
        practice_qs = repo.list_questions_for_topic(
            for_loop_topic.id, role=QuestionRole.TARGETED_PRACTICE
        )
        transfer_qs = repo.list_questions_for_topic(
            for_loop_topic.id, role=QuestionRole.TRANSFER_CHECK
        )

        assert len(initial_qs) == 1
        assert len(followup_qs) == 1
        assert len(practice_qs) == 1
        assert len(transfer_qs) == 2
        assert initial_qs[0].standard_answer == "3"


def test_foreign_key_constraints_reject_orphan_records_and_restrict_deletes(
    session_factory: sessionmaker[Session],
) -> None:
    """2. Verify SQLite foreign keys reject orphan references and restrict deleting referenced rows."""
    with pytest.raises(IntegrityError):
        with transactional_session(session_factory) as session:
            orphan_material = LearningMaterial(
                id="mat_orphan",
                topic_id="non_existent_topic_id",
                title="Orphan",
                summary="Orphan",
                content_body="Orphan",
            )
            session.add(orphan_material)

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        topic = repo.get_topic_by_slug("py-variable-assignment")
        assert topic is not None
        topic_id = topic.id

    # Attempting to delete a KnowledgeTopic that has dependent materials/questions is restricted
    with pytest.raises(IntegrityError):
        with transactional_session(session_factory) as session:
            session.execute(
                text("DELETE FROM knowledge_topics WHERE id = :tid"),
                {"tid": topic_id},
            )


def test_attempt_persistence_idempotency_and_immutability(
    session_factory: sessionmaker[Session],
) -> None:
    """4. Verify Attempt persistence, topic match validation, idempotency, and immutability."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)

        var_topic = repo.get_topic_by_slug("py-variable-assignment")
        loop_topic = repo.get_topic_by_slug("py-for-loop")
        assert var_topic is not None and loop_topic is not None

        var_q = repo.list_questions_for_topic(
            var_topic.id, role=QuestionRole.INITIAL
        )[0]
        loop_q = repo.list_questions_for_topic(
            loop_topic.id, role=QuestionRole.INITIAL
        )[0]

        learning_session = repo.create_session(
            topic_id=var_topic.id,
            current_question_id=var_q.id,
        )

        # Submitting an attempt for a question from a different topic must be rejected
        with pytest.raises(DomainRuleViolationError, match="does not match session topic"):
            repo.record_attempt(
                session_id=learning_session.id,
                question_id=loop_q.id,
                submitted_answer="3",
            )

        # Record valid attempt with idempotency key
        attempt_1 = repo.record_attempt(
            session_id=learning_session.id,
            question_id=var_q.id,
            submitted_answer="20 25",
            is_correct=False,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
            evaluation_summary="Learner treated assignment as reactive formula.",
            idempotency_key="idem_attempt_001",
        )
        attempt_duplicate = repo.record_attempt(
            session_id=learning_session.id,
            question_id=var_q.id,
            submitted_answer="different text ignored on duplicate key",
            idempotency_key="idem_attempt_001",
        )
        assert attempt_1.id == attempt_duplicate.id
        assert attempt_1.submitted_answer == "20 25"
        assert attempt_1.question_version == var_q.version

    # Attempting to overwrite raw submitted_answer or delete Attempt must raise ImmutableRecordError
    with pytest.raises(ImmutableRecordError, match="submitted_answer"):
        with transactional_session(session_factory) as session:
            att = session.scalar(select(Attempt))
            assert att is not None
            att.submitted_answer = "tampered answer"

    with pytest.raises(ImmutableRecordError, match="cannot be deleted"):
        with transactional_session(session_factory) as session:
            att = session.scalar(select(Attempt))
            assert att is not None
            session.delete(att)

    with pytest.raises(ImmutableRecordError, match="once evaluation_status is 'evaluated'"):
        with transactional_session(session_factory) as session:
            att = session.scalar(select(Attempt))
            assert att is not None
            att.is_correct = True


def test_question_update_version_enforcement_and_attempt_snapshot_traceability(
    session_factory: sessionmaker[Session],
) -> None:
    """Verify historical attempts retain question_snapshot_json and unversioned edits are blocked."""
    import copy

    raw_pack = load_content_pack_file()

    with transactional_session(session_factory) as session:
        import_content_pack(session, raw_pack)
        repo = LearningRepository(session)
        topic = repo.get_topic_by_slug("py-variable-assignment")
        assert topic is not None
        q_initial = repo.list_questions_for_topic(
            topic.id, role=QuestionRole.INITIAL
        )[0]
        original_prompt = q_initial.prompt_text
        original_std_answer = q_initial.standard_answer

        learning_session = repo.create_session(
            topic_id=topic.id, current_question_id=q_initial.id
        )
        attempt = repo.record_attempt(
            session_id=learning_session.id,
            question_id=q_initial.id,
            submitted_answer="20 15",
            is_correct=True,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )
        attempt_id = attempt.id
        assert attempt.question_version == 1
        assert attempt.question_snapshot_json["standard_answer"] == original_std_answer

    # Modifying question standard_answer without incrementing version must fail when attempts exist
    mutated_pack_no_bump = copy.deepcopy(raw_pack)
    mutated_pack_no_bump["topics"][0]["questions"][0]["standard_answer"] = "30 15"
    with pytest.raises(DomainRuleViolationError, match="requires incrementing version"):
        with transactional_session(session_factory) as session:
            import_content_pack(session, mutated_pack_no_bump)

    # Incrementing version to 2 succeeds while historical attempt retains version 1 snapshot
    mutated_pack_v2 = copy.deepcopy(raw_pack)
    mutated_pack_v2["topics"][0]["questions"][0]["context_snippet"] = (
        "a = 10\nb = a + 5\na = 30\nprint(a, b)"
    )
    mutated_pack_v2["topics"][0]["questions"][0]["standard_answer"] = "30 15"
    mutated_pack_v2["topics"][0]["questions"][0]["version"] = 2

    with transactional_session(session_factory) as session:
        import_content_pack(session, mutated_pack_v2)
        updated_q = session.get(Question, "q_py_var_initial_01")
        historical_att = session.get(Attempt, attempt_id)
        assert updated_q is not None and historical_att is not None
        assert updated_q.version == 2
        assert updated_q.standard_answer == "30 15"
        assert historical_att.question_version == 1
        assert historical_att.question_snapshot_json["version"] == 1
        assert (
            historical_att.question_snapshot_json["standard_answer"]
            == original_std_answer
        )
        assert historical_att.question_snapshot_json["prompt_text"] == original_prompt


def test_competing_hypotheses_evidence_links_and_insufficient_evidence_state(
    session_factory: sessionmaker[Session],
) -> None:
    """5. Verify multiple competing hypotheses, evidence source tracking, and insufficient_evidence."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)

        loop_topic = repo.get_topic_by_slug("py-for-loop")
        assert loop_topic is not None
        initial_q = repo.list_questions_for_topic(
            loop_topic.id, role=QuestionRole.INITIAL
        )[0]
        followup_q = repo.list_questions_for_topic(
            loop_topic.id, role=QuestionRole.DIAGNOSTIC_FOLLOWUP
        )[0]

        learning_session = repo.create_session(
            topic_id=loop_topic.id,
            current_question_id=initial_q.id,
        )
        repo.transition_session_status(learning_session, SessionStatus.DIAGNOSING)

        initial_attempt = repo.record_attempt(
            session_id=learning_session.id,
            question_id=initial_q.id,
            submitted_answer="3",
            is_correct=True,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
            evaluation_summary="Output matches 3, but no trace reasoning was provided.",
        )

        diag_case = repo.create_diagnostic_case(
            session_id=learning_session.id,
            trigger_attempt_id=initial_attempt.id,
            uncertainty_note="Answer 3 could come from valid trace (0+1+2) or range(3)=[1,2] misconception.",
        )
        repo.transition_diagnostic_case(
            diag_case,
            DiagnosticCaseStatus.INITIAL_EVALUATED,
            action="evaluate_initial_attempt",
            reason="Initial answer has no intermediate state explanation.",
            uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
        )
        repo.transition_diagnostic_case(
            diag_case,
            DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
            action="flag_insufficient_evidence",
            reason="Two competing hypotheses remain indistinguishable from single output '3'.",
            uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
        )
        assert diag_case.status == DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE.value

        # Create two competing hypotheses on the same DiagnosticCase
        hyp_memorized = repo.add_hypothesis(
            diagnostic_case_id=diag_case.id,
            error_code="loop_memorized_result_without_trace",
            name="仅凭直觉或记忆写出结果，未追踪每轮状态",
            description="只给出 3，缺失每轮循环变量变化说明。",
            confidence=0.48,
            status=HypothesisStatus.INSUFFICIENT_EVIDENCE,
            missing_evidence_desc="需要每轮 total 变化序列证据",
        )
        hyp_range_one = repo.add_hypothesis(
            diagnostic_case_id=diag_case.id,
            error_code="range_start_at_one",
            name="误以为 range(3) 生成 1 和 2（1+2 碰巧等于 3）",
            description="认为循环从 1 开始执行两轮得到 1+2=3。",
            confidence=0.35,
            status=HypothesisStatus.CANDIDATE,
            missing_evidence_desc="需要确认第一轮打印值是否为 0",
        )
        assert len(diag_case.hypotheses) == 2

        # Evidence without source_ref must be rejected
        with pytest.raises(DomainRuleViolationError, match="source_ref"):
            repo.record_evidence(
                hypothesis_id=hyp_memorized.id,
                source_type=EvidenceSourceType.INITIAL_ATTEMPT,
                source_ref="   ",
                relation=EvidenceRelation.SUPPORTS,
                summary="Only final number 3 provided.",
            )

        # Attach supporting evidence to hyp_memorized from initial attempt
        ev_1 = repo.record_evidence(
            hypothesis_id=hyp_memorized.id,
            attempt_id=initial_attempt.id,
            source_type=EvidenceSourceType.INITIAL_ATTEMPT,
            source_ref=initial_attempt.id,
            relation=EvidenceRelation.SUPPORTS,
            summary="学习者仅提交了数字 3，未包含每轮状态说明。",
            reliability_note="Initial short answer",
        )

        # Select discriminating follow-up question and record learner's response
        repo.transition_diagnostic_case(
            diag_case,
            DiagnosticCaseStatus.QUESTION_SELECTED,
            action=InterventionAction.ASK_FOLLOWUP.value,
            reason="Select follow-up asking for per-iteration print(total) output.",
        )
        followup_attempt = repo.record_attempt(
            session_id=learning_session.id,
            question_id=followup_q.id,
            submitted_answer="依次打印 0、1、3",
            is_correct=True,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )

        # Attach contradicting evidence to both error hypotheses based on follow-up response
        ev_2 = repo.record_evidence(
            hypothesis_id=hyp_range_one.id,
            attempt_id=followup_attempt.id,
            source_type=EvidenceSourceType.FOLLOWUP_RESPONSE,
            source_ref=followup_attempt.id,
            relation=EvidenceRelation.CONTRADICTS,
            summary="学习者准确写出第一轮输出为 0，排除 range(3) 从 1 开始的假设。",
        )
        ev_3 = repo.record_evidence(
            hypothesis_id=hyp_memorized.id,
            attempt_id=followup_attempt.id,
            source_type=EvidenceSourceType.FOLLOWUP_RESPONSE,
            source_ref=followup_attempt.id,
            relation=EvidenceRelation.CONTRADICTS,
            summary="学习者完整写出 0、1、3 每轮累加状态。",
        )

        repo.update_hypothesis(
            hyp_range_one,
            new_status=HypothesisStatus.RULED_OUT,
            new_confidence=0.05,
            reason="Follow-up response confirmed range starts at 0.",
        )
        repo.update_hypothesis(
            hyp_memorized,
            new_status=HypothesisStatus.LOWERED,
            new_confidence=0.15,
            reason="Learner demonstrated accurate per-iteration state tracking.",
        )

        assert ev_1.relation == EvidenceRelation.SUPPORTS.value
        assert ev_2.relation == EvidenceRelation.CONTRADICTS.value
        assert ev_3.relation == EvidenceRelation.CONTRADICTS.value
        assert hyp_range_one.status == HypothesisStatus.RULED_OUT.value
        assert hyp_memorized.status == HypothesisStatus.LOWERED.value


def test_decision_event_append_only_immutability(
    session_factory: sessionmaker[Session],
) -> None:
    """6. Verify DecisionEvent is strictly append-only (no update, no delete)."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        topic = repo.get_topic_by_slug("py-range-function")
        assert topic is not None
        learning_session = repo.create_session(topic_id=topic.id)

        evt_1 = repo.append_decision_event(
            session_id=learning_session.id,
            event_type="session_started",
            from_state=None,
            to_state=SessionStatus.ACTIVE.value,
            action="start_session",
            reason="Learner started session on py-range-function.",
            idempotency_key="evt_start_001",
        )
        evt_2 = repo.append_decision_event(
            session_id=learning_session.id,
            event_type="diagnostic_check",
            from_state=SessionStatus.ACTIVE.value,
            to_state=SessionStatus.DIAGNOSING.value,
            action="enter_diagnosis",
            reason="Check candidate misconceptions.",
        )
        assert evt_1.id != evt_2.id
        assert len(learning_session.decision_events) == 2

    # Updating a DecisionEvent must fail
    with pytest.raises(ImmutableRecordError, match="append-only"):
        with transactional_session(session_factory) as session:
            evt = session.scalar(select(DecisionEvent))
            assert evt is not None
            evt.reason = "mutated reason"

    # Deleting a DecisionEvent must fail
    with pytest.raises(ImmutableRecordError, match="cannot be deleted"):
        with transactional_session(session_factory) as session:
            evt = session.scalar(select(DecisionEvent))
            assert evt is not None
            session.delete(evt)


def test_illegal_state_transitions_are_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    """7. Verify illegal state transitions on Session, DiagnosticCase, and Hypothesis are rejected."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        topic = repo.get_topic_by_slug("py-conditional-branching")
        assert topic is not None
        q_initial = repo.list_questions_for_topic(
            topic.id, role=QuestionRole.INITIAL
        )[0]

        learning_session = repo.create_session(
            topic_id=topic.id, current_question_id=q_initial.id
        )

        # Session cannot jump directly from ACTIVE to COMPLETED without TRANSFER_CHECKING
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_session_status(learning_session, SessionStatus.COMPLETED)

        attempt = repo.record_attempt(
            session_id=learning_session.id,
            question_id=q_initial.id,
            submitted_answer="B",
            is_correct=False,
        )
        diag_case = repo.create_diagnostic_case(
            session_id=learning_session.id,
            trigger_attempt_id=attempt.id,
        )

        # DiagnosticCase cannot jump directly from COLLECTING_ATTEMPT to RESOLVED
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.RESOLVED,
                action="premature_resolve",
                reason="Illegal shortcut.",
            )

        # The newly supported edge still requires evidence from the selected question.
        q_followup = repo.list_questions_for_topic(
            topic.id, role=QuestionRole.DIAGNOSTIC_FOLLOWUP
        )[0]
        diag_case.status = DiagnosticCaseStatus.QUESTION_SELECTED.value
        diag_case.current_followup_question_id = q_followup.id
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.INTERVENTION_SELECTED,
                action="premature_intervention",
                reason="The learner has not answered the selected follow-up.",
            )

        hyp = repo.add_hypothesis(
            diagnostic_case_id=diag_case.id,
            error_code="cond_elif_treated_as_independent_if",
            name="忽略 elif 短路",
            description="误以为 elif 会继续执行",
            confidence=0.6,
            status=HypothesisStatus.CANDIDATE,
        )
        repo.update_hypothesis(
            hyp,
            new_status=HypothesisStatus.RULED_OUT,
            new_confidence=0.0,
            reason="Ruled out by evidence.",
        )

        # Once a Hypothesis is RULED_OUT, transitioning it back to CONFIRMED is rejected
        with pytest.raises(InvalidStateTransitionError):
            repo.update_hypothesis(
                hyp,
                new_status=HypothesisStatus.CONFIRMED,
                new_confidence=0.9,
                reason="Cannot revive ruled out hypothesis.",
            )


def test_mastery_requires_transfer_verification_and_traceable_reason(
    session_factory: sessionmaker[Session],
) -> None:
    """4 & 7. Verify a single correct initial answer CANNOT mark mastery as STABLE; transfer_check is required."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        topic = repo.get_topic_by_slug("py-list-indexing")
        assert topic is not None

        q_initial = repo.list_questions_for_topic(
            topic.id, role=QuestionRole.INITIAL
        )[0]
        q_transfer = repo.list_questions_for_topic(
            topic.id, role=QuestionRole.TRANSFER_CHECK
        )[0]

        learning_session = repo.create_session(
            topic_id=topic.id, current_question_id=q_initial.id
        )

        # Learner answers initial question correctly
        initial_correct_attempt = repo.record_attempt(
            session_id=learning_session.id,
            question_id=q_initial.id,
            submitted_answer="80 100",
            is_correct=True,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )

        # Rule: Attempting to mark KnowledgeState as STABLE based only on initial_correct_attempt MUST fail!
        with pytest.raises(UnverifiedMasteryError):
            repo.update_knowledge_state(
                session_id=learning_session.id,
                topic_id=topic.id,
                target_status=KnowledgeMasteryStatus.STABLE,
                reason="Learner got the first question right.",
                transfer_attempt_id=initial_correct_attempt.id,
            )

        # Updating to NEEDS_PRACTICE with traceable reason succeeds and records DecisionEvent
        ks_intermediate = repo.update_knowledge_state(
            session_id=learning_session.id,
            topic_id=topic.id,
            target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
            reason="Initial answer correct, awaiting transfer verification.",
            unresolved_error_codes=["list_one_based_indexing"],
        )
        assert ks_intermediate.status == KnowledgeMasteryStatus.NEEDS_PRACTICE.value
        first_decision_event_id = ks_intermediate.last_decision_event_id
        assert first_decision_event_id is not None

        # Failed transfer attempt also cannot mark KnowledgeState as STABLE
        failed_transfer = repo.record_attempt(
            session_id=learning_session.id,
            question_id=q_transfer.id,
            submitted_answer="[20, 20, 20]",
            is_correct=False,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )
        with pytest.raises(UnverifiedMasteryError):
            repo.update_knowledge_state(
                session_id=learning_session.id,
                topic_id=topic.id,
                target_status=KnowledgeMasteryStatus.STABLE,
                reason="Attempted transfer check.",
                transfer_attempt_id=failed_transfer.id,
            )

        # Schedule a ReviewItem due to failed transfer check
        review_item = repo.schedule_review_item(
            topic_id=topic.id,
            session_id=learning_session.id,
            trigger_reason="最近一次迁移验证失败，需复习列表索引差值计算。",
        )
        assert review_item.id.startswith("rev_")

        # Retrying the same failed transfer question CANNOT promote KnowledgeState to STABLE
        retry_same_transfer = repo.record_attempt(
            session_id=learning_session.id,
            question_id=q_transfer.id,
            submitted_answer="[10, 10, 10]",
            is_correct=True,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )
        with pytest.raises(UnverifiedMasteryError, match="retried transfer"):
            repo.update_knowledge_state(
                session_id=learning_session.id,
                topic_id=topic.id,
                target_status=KnowledgeMasteryStatus.STABLE,
                reason="Retried same question after failing.",
                transfer_attempt_id=retry_same_transfer.id,
            )

        # Passing an independent fresh transfer_check attempt allows transitioning KnowledgeState to STABLE
        transfer_qs = repo.list_questions_for_topic(
            topic.id, role=QuestionRole.TRANSFER_CHECK
        )
        assert len(transfer_qs) >= 2
        q_transfer_fresh = transfer_qs[1]
        passed_transfer = repo.record_attempt(
            session_id=learning_session.id,
            question_id=q_transfer_fresh.id,
            submitted_answer="12 31 6",
            is_correct=True,
            evaluation_status=AttemptEvaluationStatus.EVALUATED,
        )
        ks_stable = repo.update_knowledge_state(
            session_id=learning_session.id,
            topic_id=topic.id,
            target_status=KnowledgeMasteryStatus.STABLE,
            reason="Passed independent fresh transfer_check question q_py_list_transfer_02.",
            unresolved_error_codes=[],
            transfer_attempt_id=passed_transfer.id,
        )
        assert ks_stable.status == KnowledgeMasteryStatus.STABLE.value
        assert ks_stable.last_transfer_attempt_id == passed_transfer.id
        assert ks_stable.last_decision_event_id != first_decision_event_id


def test_isolated_temp_db_does_not_create_or_modify_dev_db(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    """9. Verify test database is completely isolated in tmp_path and does not touch backend/unlearnloop.db."""
    default_dev_db = BACKEND_DIR / "unlearnloop.db"
    existed_before = default_dev_db.exists()
    mtime_before = default_dev_db.stat().st_mtime if existed_before else None

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        assert session.scalar(select(KnowledgeTopic)) is not None

    assert "test_unlearnloop.db" in test_settings.database_url
    if not existed_before:
        assert not default_dev_db.exists()
    else:
        assert default_dev_db.stat().st_mtime == mtime_before
