"""Objective evaluator for original IELTS reading practice items."""
from app.domain.enums import EvidenceRelation, EvidenceSourceType, HypothesisStatus, QuestionRole
from app.evaluation.rule_evaluator import RuleEvaluationResult, RuleEvidenceDraft, RuleHypothesisDraft
from app.persistence.models import Attempt, KnowledgeTopic, Question


class IeltsReadingEvaluator:
    """Match configured answer keys; treat wrong-answer mappings as tentative evidence."""
    def evaluate_attempt(self, *, attempt: Attempt, question: Question, topic: KnowledgeTopic) -> RuleEvaluationResult:
        rubric = question.evaluation_rubric or {}
        accepted = {" ".join(str(v).casefold().split()) for v in rubric.get("accepted_answers", [question.standard_answer])}
        answer = " ".join(attempt.submitted_answer.casefold().split())
        correct = answer in accepted
        summary = ("答案与本题设定的阅读证据相符。" if correct else
                   "答案与本题设定的证据不符；仅凭这一题不足以确定错误原因。")
        patterns = {str(p.get("error_code")): p for p in (topic.common_error_patterns or [])}
        candidates, evidence = [], []
        if not correct:
            for mapping in rubric.get("candidate_error_mappings", []):
                if " ".join(str(mapping.get("answer", "")).casefold().split()) != answer:
                    continue
                code = str(mapping.get("error_code", ""))
                pattern = patterns.get(code)
                if not pattern:
                    continue
                candidates.append(RuleHypothesisDraft(
                    error_code=code, name=str(pattern.get("name", code)),
                    description=str(pattern.get("description", "")), heuristic_confidence=0.35,
                    initial_status=HypothesisStatus.CANDIDATE,
                    missing_evidence_desc="需要另一道区分性问题验证；当前权重是启发式提示。"))
                evidence.append(RuleEvidenceDraft(
                    target_error_code=code, source_type=EvidenceSourceType.RULE_CHECK,
                    source_ref=f"attempt:{attempt.id}", relation=EvidenceRelation.SUPPORTS,
                    summary=f"本次作答“{attempt.submitted_answer[:80]}”。{mapping.get('evidence_summary', '这一选择与候选原因相容，但单题证据有限。')}",
                    reliability_note="原题客观选项匹配；不是统计概率或确定诊断。"))
        return RuleEvaluationResult(
            attempt_id=attempt.id, question_id=question.id, question_role=QuestionRole(question.question_role),
            answer_matches_standard=correct, has_reasoning_or_trace=False,
            is_fully_verified_correct=correct, requires_agent_diagnosis=not correct,
            summary=summary, candidate_hypotheses=candidates, evidence_drafts=evidence)
