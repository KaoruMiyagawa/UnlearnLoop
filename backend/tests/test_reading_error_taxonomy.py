from types import SimpleNamespace

import pytest

from app.domain.enums import EvidenceRelation, HypothesisStatus
from app.evaluation.ielts_reading_evaluator import IeltsReadingEvaluator
from app.evaluation.reading_error_taxonomy import READING_ERROR_CATEGORIES, TAXONOMY_VERSION


@pytest.mark.parametrize("domain", ["ielts_academic", "ielts_general_training"])
def test_unmapped_wrong_reading_answer_remains_uncertain(domain):
    topic = SimpleNamespace(domain_code=domain, common_error_patterns=[])
    question = SimpleNamespace(id="q", question_role="initial", standard_answer="B",
                               evaluation_rubric={"accepted_answers": ["B"]})
    attempt = SimpleNamespace(id="attempt", submitted_answer="A")
    result = IeltsReadingEvaluator().evaluate_attempt(attempt=attempt, question=question, topic=topic)
    assert not result.answer_matches_standard
    assert result.candidate_hypotheses[0].initial_status == HypothesisStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_drafts[0].relation == EvidenceRelation.NEUTRAL
    assert "B" not in result.evidence_drafts[0].summary


def test_taxonomy_is_versioned_and_includes_safe_fallback():
    assert TAXONOMY_VERSION == "reading-error-dna-v1"
    assert len(READING_ERROR_CATEGORIES) == 9
    assert "insufficient_evidence" in READING_ERROR_CATEGORIES


@pytest.mark.parametrize("answer,code,relation", [
    ("A", "true_false_not_given", EvidenceRelation.SUPPORTS),
    ("B", "passage_location", EvidenceRelation.SUPPORTS),
    ("C", "true_false_not_given", EvidenceRelation.CONTRADICTS),
])
def test_versioned_followup_produces_answer_specific_evidence(answer, code, relation):
    rubric = {
        "accepted_answers": ["C"], "diagnostic_version": TAXONOMY_VERSION,
        "diagnostic_evidence_mappings": [
            {"answer": "A", "error_code": "true_false_not_given", "relation": "supports"},
            {"answer": "B", "error_code": "passage_location", "relation": "supports"},
            {"answer": "C", "error_code": "true_false_not_given", "relation": "contradicts"},
        ],
    }
    question = SimpleNamespace(id="followup", version=2, question_role="diagnostic_followup",
                               standard_answer="C", evaluation_rubric=rubric)
    result = IeltsReadingEvaluator().evaluate_attempt(
        attempt=SimpleNamespace(id="att-1", submitted_answer=answer), question=question,
        topic=SimpleNamespace(common_error_patterns=[]))
    assert len(result.evidence_drafts) == 1
    assert result.evidence_drafts[0].target_error_code == code
    assert result.evidence_drafts[0].relation == relation
    assert result.evidence_drafts[0].source_ref == f"{TAXONOMY_VERSION}:followup:v2:att-1"
    assert not result.candidate_hypotheses


def test_unknown_diagnostic_version_produces_no_followup_evidence():
    question = SimpleNamespace(id="q", version=1, question_role="diagnostic_followup", standard_answer="A",
        evaluation_rubric={"diagnostic_version": "unknown", "diagnostic_evidence_mappings": [
            {"answer": "B", "error_code": "passage_location", "relation": "supports"}]})
    result = IeltsReadingEvaluator().evaluate_attempt(
        attempt=SimpleNamespace(id="att", submitted_answer="B"), question=question,
        topic=SimpleNamespace(common_error_patterns=[]))
    assert result.evidence_drafts == []


def test_followup_evidence_updates_existing_hypotheses_once(session_factory, test_settings):
    from pathlib import Path
    from app.decision.agent_engine import DiagnosticAgentEngine
    from app.model_provider.fake import FakeModelProvider
    from app.persistence.models import Question
    from app.persistence.repositories import LearningRepository
    from app.persistence.seed import import_content_pack

    with session_factory() as db:
        import_content_pack(db, pack_path=Path(__file__).parents[1] / "app/content/ielts_reading_english_pack.json")
        repo = LearningRepository(db)
        topic = repo.get_topic_by_slug("ielts-acad-reading-english")
        session = repo.create_session(topic_id=topic.id, current_question_id="ielts-acad-english-initial")
        initial = repo.record_attempt(session_id=session.id, question_id="ielts-acad-english-initial", submitted_answer="A")
        case = repo.create_diagnostic_case(session_id=session.id, trigger_attempt_id=initial.id)
        h1 = repo.add_hypothesis(diagnostic_case_id=case.id, error_code="true_false_not_given", name="TFNG", description="candidate", confidence=0.35)
        h2 = repo.add_hypothesis(diagnostic_case_id=case.id, error_code="passage_location", name="location", description="candidate", confidence=0.35)
        question = db.get(Question, "ielts-acad-english-diagnostic_followup")
        question.evaluation_rubric = {"accepted_answers": ["C"], "diagnostic_version": TAXONOMY_VERSION,
            "diagnostic_evidence_mappings": [
                {"answer": "A", "error_code": h1.error_code, "relation": "supports"},
                {"answer": "A", "error_code": h2.error_code, "relation": "contradicts"},
            ]}
        attempt = repo.record_attempt(session_id=session.id, question_id=question.id, submitted_answer="A")
        result = IeltsReadingEvaluator().evaluate_attempt(attempt=attempt, question=question, topic=topic)
        engine = DiagnosticAgentEngine(db, FakeModelProvider(), settings=test_settings)
        engine._apply_rule_pre_evaluation(diag_case=case, attempt=attempt, rule_result=result)
        engine._apply_rule_pre_evaluation(diag_case=case, attempt=attempt, rule_result=result)
        db.refresh(h1)
        db.refresh(h2)
        assert h1.status == HypothesisStatus.SUPPORTED.value
        assert h2.status == HypothesisStatus.LOWERED.value
        assert len(h1.evidence_links) == len(h2.evidence_links) == 1
