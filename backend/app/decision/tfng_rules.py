"""Auditable TFNG v1 decisions; no semantic model inference or confirmed diagnoses."""
from app.decision.schemas import AgentDecisionProposal, AgentToolCallProposal
from app.domain.enums import QuestionRole, UncertaintyLevel
from app.evaluation.reading_error_taxonomy import TAXONOMY_VERSION


def tfng_proposal(session, case, repo):
    questions = repo.list_questions_for_topic(session.topic_id)
    initial = next((q for q in questions if q.question_role == "initial"), None)
    if (initial is None or (initial.evaluation_rubric or {}).get("diagnostic_protocol") != "tfng-v1"
            or initial.evaluation_rubric.get("diagnostic_version") != TAXONOMY_VERSION):
        return None
    answered = {a.question_id for a in repo.list_attempts_for_session(session.id)}
    followups = {q.id.rsplit("-", 1)[-1]: q for q in questions if q.question_role == "diagnostic_followup"}
    for stage in ("locate", "logic"):
        question = followups.get(stage)
        if question is not None and question.id not in answered:
            reason = question.evaluation_rubric["discriminating_rationale"]
            return AgentDecisionProposal(reasoning="TFNG v1 规则：" + reason,
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note="微任务证据有限，原因尚未确认。",
                selected_tool=AgentToolCallProposal(tool_name="select_diagnostic_followup", arguments={
                    "followup_question_id": question.id, "target_error_codes": question.evaluation_rubric["target_error_codes"],
                    "discriminating_reason": "TFNG v1：" + reason}))
    states = {h.error_code: h.status for h in case.hypotheses}
    target = None
    for candidate, other in (("true_false_not_given", "passage_location"), ("passage_location", "true_false_not_given")):
        if states.get(candidate) == "supported" and states.get(other) == "lowered":
            target = candidate
    practice = next((q for q in questions if q.question_role == QuestionRole.TARGETED_PRACTICE.value
                     and target and q.evaluation_rubric.get("target_error_codes") == [target]
                     and q.id not in answered), None)
    reason = (f"TFNG v1：{target} 获得支持，另一原因被削弱；选择对应训练，仍不确认能力缺陷。" if practice else
              "TFNG v1：两项表现尚不能形成可靠单一分流，或缺少匹配训练；保留不确定性，不分配无关练习。")
    return AgentDecisionProposal(reasoning=reason, uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
        uncertainty_note="尚需独立验证；本阶段不评定长期掌握。",
        selected_tool=AgentToolCallProposal(tool_name="assign_targeted_practice", arguments={
            "practice_question_id": practice.id if practice else None,
            "target_error_codes": [target] if practice else [], "practice_reason": reason}))
