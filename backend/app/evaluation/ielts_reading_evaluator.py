"""Objective evaluator for original IELTS reading practice items."""
from app.domain.enums import EvidenceRelation, EvidenceSourceType, HypothesisStatus, QuestionRole
from app.evaluation.rule_evaluator import RuleEvaluationResult, RuleEvidenceDraft, RuleHypothesisDraft
from app.evaluation.reading_error_taxonomy import READING_ERROR_CATEGORIES, TAXONOMY_VERSION
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
        # Only explicitly versioned, answer-specific follow-up rubrics may
        # supply evidence. A correct answer alone cannot prove a hypothesis.
        if (question.question_role == QuestionRole.DIAGNOSTIC_FOLLOWUP.value
                and rubric.get("diagnostic_version") == TAXONOMY_VERSION):
            for mapping in rubric.get("diagnostic_evidence_mappings", []):
                if " ".join(str(mapping.get("answer", "")).casefold().split()) != answer:
                    continue
                code = str(mapping.get("error_code", ""))
                relation = mapping.get("relation")
                if code not in READING_ERROR_CATEGORIES or relation not in {"supports", "contradicts", "neutral"}:
                    continue
                evidence.append(RuleEvidenceDraft(
                    target_error_code=code, source_type=EvidenceSourceType.RULE_CHECK,
                    source_ref=f"{TAXONOMY_VERSION}:{question.id}:v{question.version}:{attempt.id}",
                    relation=EvidenceRelation(relation),
                    summary=str(mapping.get("summary") or "追问作答提供了新的待核验证据。"),
                    reliability_note="版本化追问规则；证据仍需独立验证。"))
            if not evidence:
                for code in rubric.get("target_error_codes", []):
                    if code in READING_ERROR_CATEGORIES:
                        evidence.append(RuleEvidenceDraft(
                            target_error_code=code, source_type=EvidenceSourceType.RULE_CHECK,
                            source_ref=f"{TAXONOMY_VERSION}:{question.id}:v{question.version}:{attempt.id}",
                            relation=EvidenceRelation.NEUTRAL,
                            summary="本次回答未匹配已审核的诊断选项，不能据此判断原因。",
                            reliability_note="不解释自由文本语义，保留不确定性。"))
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
                    source_ref=(f"{TAXONOMY_VERSION}:{question.id}:v{question.version}:{attempt.id}"
                                if rubric.get("diagnostic_protocol") == "tfng-v1" else f"attempt:{attempt.id}"), relation=EvidenceRelation.SUPPORTS,
                    summary=f"本次作答“{attempt.submitted_answer[:80]}”。{mapping.get('evidence_summary', '这一选择与候选原因相容，但单题证据有限。')}",
                    reliability_note="原题客观选项匹配；不是统计概率或确定诊断。"))
            if not candidates and question.question_role == QuestionRole.INITIAL.value:
                # An unmapped answer establishes only that the configured answer did
                # not match. It cannot establish a particular reading weakness.
                code = "insufficient_evidence"
                candidates.append(RuleHypothesisDraft(
                    error_code=code, name=READING_ERROR_CATEGORIES[code],
                    description="当前作答不足以区分具体错误原因。", heuristic_confidence=0.0,
                    initial_status=HypothesisStatus.INSUFFICIENT_EVIDENCE,
                    missing_evidence_desc="需要结合原文证据及后续作答进一步判断。"))
                evidence.append(RuleEvidenceDraft(
                    target_error_code=code, source_type=EvidenceSourceType.RULE_CHECK,
                    source_ref=f"attempt:{attempt.id}", relation=EvidenceRelation.NEUTRAL,
                    summary="本次答案未匹配题目设定的答案；尚无足够证据判断原因。",
                    reliability_note="客观答题结果；不构成能力诊断。"))
        return RuleEvaluationResult(
            attempt_id=attempt.id, question_id=question.id, question_role=QuestionRole(question.question_role),
            answer_matches_standard=correct, has_reasoning_or_trace=False,
            is_fully_verified_correct=correct, requires_agent_diagnosis=not correct,
            summary=summary, candidate_hypotheses=candidates, evidence_drafts=evidence)
