"""Whitelisted tool registry and domain-validated executor for the Diagnostic Agent.

Per ARCHITECTURE.md Section 6 & Stage 3 Section 4:
- The model CANNOT directly mutate the database, run arbitrary code, or call non-whitelisted tools.
- Every tool call is validated against:
  1. The explicit `AgentToolName` whitelist,
  2. Its Pydantic argument schema, and
  3. Stage 2 domain and state transition rules.
"""

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.decision.heuristics import rank_followup_questions
from app.decision.schemas import (
    AgentToolCallProposal,
    AssignPracticeArgs,
    AssignTransferArgs,
    HypothesisUpdateProposal,
    ProvideExplanationArgs,
    SelectFollowupArgs,
    UpdateKnowledgeStateArgs,
)
from app.domain.enums import (
    AgentToolName,
    DiagnosticCaseStatus,
    EvidenceSourceType,
    HypothesisStatus,
    InterventionAction,
    KnowledgeMasteryStatus,
    QuestionRole,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.exceptions import DomainRuleViolationError
from app.persistence.models import Attempt, DiagnosticCase, Hypothesis, LearningSession
from app.persistence.repositories import LearningRepository


class IllegalAgentToolCallError(DomainRuleViolationError):
    """Raised when the Agent attempts to invoke an unauthorized or schema-invalid tool."""


WHITELISTED_AGENT_TOOLS: frozenset[str] = frozenset(t.value for t in AgentToolName)


def validate_whitelisted_tool_name(tool_name: str) -> AgentToolName:
    """Verify `tool_name` belongs to the authorized `AgentToolName` whitelist."""
    normalized = tool_name.strip()
    if normalized not in WHITELISTED_AGENT_TOOLS:
        raise IllegalAgentToolCallError(
            f"Unauthorized Agent tool '{tool_name}'. Allowed tools: {sorted(WHITELISTED_AGENT_TOOLS)}"
        )
    return AgentToolName(normalized)


class AgentToolExecutor:
    """Executes whitelisted Agent tools against `LearningRepository` with strict domain checks."""

    def __init__(self, repo: LearningRepository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # Tool 1: read_material_and_question (Read-Only Context Tool)
    # ------------------------------------------------------------------

    def read_material_and_question(
        self,
        *,
        topic_id: str,
        question_id: str,
    ) -> dict[str, Any]:
        topic = self.repo.session.get(
            type(self.repo.list_topics()[0]) if self.repo.list_topics() else None,  # type: ignore[arg-type]
            topic_id,
        ) if False else None  # Resolved cleanly via repo below
        topics = [t for t in self.repo.list_topics() if t.id == topic_id]
        if not topics:
            raise DomainRuleViolationError(f"Topic {topic_id} not found.")
        topic = topics[0]

        questions = [
            q for q in self.repo.list_questions_for_topic(topic_id) if q.id == question_id
        ]
        if not questions:
            raise DomainRuleViolationError(
                f"Question {question_id} not found under topic {topic_id}."
            )
        question = questions[0]

        return {
            "topic": {
                "id": topic.id,
                "slug": topic.slug,
                "title": topic.title,
                "summary": topic.summary,
                "common_error_patterns": topic.common_error_patterns,
            },
            "materials": [
                {
                    "id": m.id,
                    "title": m.title,
                    "summary": m.summary,
                }
                for m in topic.materials
            ],
            "question": {
                "id": question.id,
                "question_role": question.question_role,
                "question_type": question.question_type,
                "prompt_text": question.prompt_text,
                "context_snippet": question.context_snippet,
                "standard_answer": question.standard_answer,
                "evaluation_rubric": question.evaluation_rubric,
                "version": question.version,
            },
        }

    # ------------------------------------------------------------------
    # Tool 2: query_attempts_and_evidence (Read-Only History Tool)
    # ------------------------------------------------------------------

    def query_attempts_and_evidence(
        self,
        *,
        learning_session: LearningSession,
        diag_case: DiagnosticCase,
    ) -> dict[str, Any]:
        return {
            "session_id": learning_session.id,
            "session_status": learning_session.status,
            "diagnostic_case_id": diag_case.id,
            "diagnostic_case_status": diag_case.status,
            "attempts": [
                {
                    "id": att.id,
                    "question_id": att.question_id,
                    "attempt_role": att.attempt_role,
                    "submitted_answer": att.submitted_answer,
                    "is_correct": att.is_correct,
                }
                for att in learning_session.attempts
            ],
            "hypotheses": [
                {
                    "id": hyp.id,
                    "error_code": hyp.error_code,
                    "name": hyp.name,
                    "confidence": hyp.confidence,
                    "status": hyp.status,
                    "missing_evidence_desc": hyp.missing_evidence_desc,
                    "evidence_links": [
                        {
                            "id": ev.id,
                            "source_type": ev.source_type,
                            "source_ref": ev.source_ref,
                            "relation": ev.relation,
                            "summary": ev.summary,
                        }
                        for ev in hyp.evidence_links
                    ],
                }
                for hyp in diag_case.hypotheses
            ],
        }

    # ------------------------------------------------------------------
    # Tool 3: upsert_hypotheses (Maintain Competing Hypotheses & Evidence)
    # ------------------------------------------------------------------

    def upsert_hypotheses(
        self,
        *,
        diag_case: DiagnosticCase,
        trigger_attempt: Attempt,
        proposals: list[HypothesisUpdateProposal],
        source_type: EvidenceSourceType,
        decision_reason: str,
    ) -> list[Hypothesis]:
        self.repo.session.refresh(diag_case)
        existing_by_code: dict[str, Hypothesis] = {
            h.error_code: h for h in diag_case.hypotheses
        }
        topic_patterns = {
            str(p["error_code"]): p
            for p in (diag_case.topic.common_error_patterns or [])
            if "error_code" in p
        }

        updated_list: list[Hypothesis] = []
        for prop in proposals:
            code = prop.error_code.strip()
            pat = topic_patterns.get(code, {})
            default_name = str(pat.get("name") or f"候选错误假设：{code}")
            default_desc = str(
                pat.get("description") or f"关于 {code} 的候选错误原因判断。"
            )

            if code not in existing_by_code:
                hyp = self.repo.add_hypothesis(
                    diagnostic_case_id=diag_case.id,
                    error_code=code,
                    name=prop.name or default_name,
                    description=prop.description or default_desc,
                    confidence=prop.heuristic_confidence,
                    status=prop.status,
                    missing_evidence_desc=prop.missing_evidence_desc,
                )
                existing_by_code[code] = hyp
            else:
                hyp = existing_by_code[code]
                if hyp.status != HypothesisStatus.RULED_OUT.value:
                    self.repo.update_hypothesis(
                        hyp,
                        new_status=prop.status,
                        new_confidence=prop.heuristic_confidence,
                        reason=decision_reason,
                        missing_evidence_desc=prop.missing_evidence_desc,
                    )

            for ev_prop in prop.evidence_items:
                self.repo.record_evidence(
                    hypothesis_id=hyp.id,
                    attempt_id=trigger_attempt.id,
                    source_type=source_type,
                    source_ref=f"agent_eval:{trigger_attempt.id}:{code}",
                    relation=ev_prop.relation,
                    summary=ev_prop.summary,
                    reliability_note="Agent structured evidence analysis (heuristic confidence, not statistical probability)",
                )
            updated_list.append(hyp)

        return updated_list

    # ------------------------------------------------------------------
    # Tool 4-8: Action Execution Dispatcher
    # ------------------------------------------------------------------

    def execute_action_tool(
        self,
        *,
        learning_session: LearningSession,
        diag_case: DiagnosticCase,
        current_attempt: Attempt,
        tool_proposal: AgentToolCallProposal,
        uncertainty_level: UncertaintyLevel,
        uncertainty_note: str | None,
    ) -> dict[str, Any]:
        """Validate and execute the Agent's chosen action tool."""
        tool_enum = validate_whitelisted_tool_name(tool_proposal.tool_name)
        raw_args = tool_proposal.arguments or {}

        # Read-only or hypothesis-only tools are valid; map them to appropriate state
        if tool_enum == AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP:
            try:
                args = SelectFollowupArgs.model_validate(raw_args)
            except ValidationError as exc:
                raise IllegalAgentToolCallError(
                    f"Invalid arguments for {tool_enum.value}: {exc.errors()}"
                ) from exc

            followup_candidates = self.repo.list_questions_for_topic(
                learning_session.topic_id, role=QuestionRole.DIAGNOSTIC_FOLLOWUP
            )
            if not followup_candidates:
                raise DomainRuleViolationError(
                    f"No diagnostic_followup questions available for topic {learning_session.topic_id}."
                )

            asked_ids = {att.question_id for att in learning_session.attempts}
            active_codes = {
                h.error_code
                for h in diag_case.hypotheses
                if h.status
                in (
                    HypothesisStatus.CANDIDATE.value,
                    HypothesisStatus.INSUFFICIENT_EVIDENCE.value,
                    HypothesisStatus.SUPPORTED.value,
                )
            } or set(args.target_error_codes)

            ranked = rank_followup_questions(
                followup_candidates,
                active_error_codes=active_codes,
                already_asked_question_ids=asked_ids,
            )

            chosen_q_id = args.followup_question_id
            valid_candidate_ids = {q.id for q in followup_candidates}
            if not chosen_q_id or chosen_q_id not in valid_candidate_ids:
                chosen_q_id = ranked[0].question_id

            diag_case.current_followup_question_id = chosen_q_id
            learning_session.current_question_id = chosen_q_id
            if learning_session.status != SessionStatus.DIAGNOSING.value:
                self.repo.transition_session_status(
                    learning_session, SessionStatus.DIAGNOSING
                )

            evt = self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.QUESTION_SELECTED,
                action=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
                reason=args.discriminating_reason,
                uncertainty_level=uncertainty_level,
                uncertainty_note=uncertainty_note,
                selected_intervention=InterventionAction.ASK_FOLLOWUP.value,
                payload_json={
                    "selected_question_id": chosen_q_id,
                    "target_error_codes": list(active_codes),
                    "heuristic_ranking": [
                        {"question_id": r.question_id, "score": r.score}
                        for r in ranked
                    ],
                },
            )
            return {
                "executed_tool": tool_enum.value,
                "selected_intervention": InterventionAction.ASK_FOLLOWUP.value,
                "selected_question_id": chosen_q_id,
                "explanation_text": None,
                "decision_event_id": evt.id,
                "knowledge_state_status": None,
            }

        if tool_enum == AgentToolName.PROVIDE_TARGETED_EXPLANATION:
            try:
                args = ProvideExplanationArgs.model_validate(raw_args)
            except ValidationError as exc:
                raise IllegalAgentToolCallError(
                    f"Invalid arguments for {tool_enum.value}: {exc.errors()}"
                ) from exc

            if learning_session.status != SessionStatus.INTERVENING.value:
                self.repo.transition_session_status(
                    learning_session, SessionStatus.INTERVENING
                )
            evt = self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.INTERVENTION_SELECTED,
                action=AgentToolName.PROVIDE_TARGETED_EXPLANATION.value,
                reason=args.explanation_text,
                uncertainty_level=uncertainty_level,
                uncertainty_note=uncertainty_note,
                selected_intervention=InterventionAction.EXPLAIN_CONCEPT.value,
                payload_json={
                    "target_error_codes": args.target_error_codes,
                    "explanation_text": args.explanation_text,
                },
            )
            if args.schedule_review:
                self.repo.schedule_review_item(
                    topic_id=learning_session.topic_id,
                    session_id=learning_session.id,
                    trigger_reason=f"概念解释后安排复习巩固：{args.explanation_text[:80]}",
                )
            return {
                "executed_tool": tool_enum.value,
                "selected_intervention": InterventionAction.EXPLAIN_CONCEPT.value,
                "selected_question_id": None,
                "explanation_text": args.explanation_text,
                "decision_event_id": evt.id,
                "knowledge_state_status": None,
            }

        if tool_enum == AgentToolName.ASSIGN_TARGETED_PRACTICE:
            try:
                args = AssignPracticeArgs.model_validate(raw_args)
            except ValidationError as exc:
                raise IllegalAgentToolCallError(
                    f"Invalid arguments for {tool_enum.value}: {exc.errors()}"
                ) from exc

            practice_qs = self.repo.list_questions_for_topic(
                learning_session.topic_id, role=QuestionRole.TARGETED_PRACTICE
            )
            answered_ids = {attempt.question_id for attempt in self.repo.list_attempts_for_session(learning_session.id)}
            practice_qs = [question for question in practice_qs if question.id not in answered_ids]
            if not practice_qs:
                reason = "没有尚未作答的针对性练习；保留不确定性，等待补充材料或人工介入。"
                learning_session.current_question_id = None
                evt = self.repo.transition_diagnostic_case(
                    diag_case, DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
                    action="practice_questions_exhausted", reason=reason,
                    uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE, uncertainty_note=reason,
                )
                self.repo.update_knowledge_state(
                    session_id=learning_session.id, topic_id=learning_session.topic_id,
                    learner_id=learning_session.learner_id, target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
                    reason=reason,
                )
                return {"executed_tool": "practice_questions_exhausted", "selected_intervention": None,
                        "selected_question_id": None, "explanation_text": reason,
                        "decision_event_id": evt.id, "knowledge_state_status": "needs_practice"}
            valid_ids = {q.id for q in practice_qs}
            chosen_practice_id = (
                args.practice_question_id
                if args.practice_question_id in valid_ids
                else practice_qs[0].id
            )
            learning_session.current_question_id = chosen_practice_id
            if learning_session.status != SessionStatus.INTERVENING.value:
                self.repo.transition_session_status(
                    learning_session, SessionStatus.INTERVENING
                )

            evt = self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.INTERVENTION_SELECTED,
                action=AgentToolName.ASSIGN_TARGETED_PRACTICE.value,
                reason=args.practice_reason,
                uncertainty_level=uncertainty_level,
                uncertainty_note=uncertainty_note,
                selected_intervention=InterventionAction.TARGETED_PRACTICE.value,
                payload_json={
                    "selected_question_id": chosen_practice_id,
                    "target_error_codes": args.target_error_codes,
                },
            )
            return {
                "executed_tool": tool_enum.value,
                "selected_intervention": InterventionAction.TARGETED_PRACTICE.value,
                "selected_question_id": chosen_practice_id,
                "explanation_text": None,
                "decision_event_id": evt.id,
                "knowledge_state_status": None,
            }

        if tool_enum == AgentToolName.ASSIGN_TRANSFER_VERIFICATION:
            try:
                args = AssignTransferArgs.model_validate(raw_args)
            except ValidationError as exc:
                raise IllegalAgentToolCallError(
                    f"Invalid arguments for {tool_enum.value}: {exc.errors()}"
                ) from exc

            self.repo.validate_transfer_readiness(learning_session, agent_selected=True)
            fresh_transfer_qs = self.repo.fresh_transfer_questions(learning_session)

            if not fresh_transfer_qs:
                # Safe degradation: do not loop the same failed transfer question or grant false mastery
                degrade_msg = (
                    f"知识点 '{diag_case.topic.slug}' 暂无未作答过的独立新情境迁移验证题；"
                    "保留待练习状态并安排复习巩固，防止同题重复猜测造成虚假掌握。"
                )
                self.repo.schedule_review_item(
                    topic_id=learning_session.topic_id,
                    session_id=learning_session.id,
                    learner_id=learning_session.learner_id,
                    trigger_reason=degrade_msg,
                )
                evt = self.repo.transition_diagnostic_case(
                    diag_case,
                    DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
                    action="exhausted_transfer_questions_degrade",
                    reason=degrade_msg,
                    uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                    uncertainty_note=degrade_msg,
                    selected_intervention=InterventionAction.SCHEDULE_REVIEW.value,
                    payload_json={
                        "degraded_mode": True,
                        "degradation_reason": degrade_msg,
                    },
                )
                return {
                    "executed_tool": "exhausted_transfer_questions_degrade",
                    "selected_intervention": InterventionAction.SCHEDULE_REVIEW.value,
                    "selected_question_id": None,
                    "explanation_text": None,
                    "decision_event_id": evt.id,
                    "knowledge_state_status": None,
                    "degraded_mode": True,
                    "degradation_reason": degrade_msg,
                }

            valid_fresh_ids = {q.id for q in fresh_transfer_qs}
            chosen_transfer_id = (
                args.transfer_question_id
                if args.transfer_question_id in valid_fresh_ids
                else fresh_transfer_qs[0].id
            )
            learning_session.current_question_id = chosen_transfer_id
            if learning_session.status != SessionStatus.TRANSFER_CHECKING.value:
                self.repo.transition_session_status(
                    learning_session, SessionStatus.TRANSFER_CHECKING
                )

            # Ensure valid intermediate state transition to TRANSFER_CHECKING
            if diag_case.status not in (
                DiagnosticCaseStatus.INTERVENTION_SELECTED.value,
                DiagnosticCaseStatus.TRANSFER_CHECKING.value,
            ):
                self.repo.transition_diagnostic_case(
                    diag_case,
                    DiagnosticCaseStatus.INTERVENTION_SELECTED,
                    action="prepare_transfer_verification",
                    reason=args.transfer_reason,
                    uncertainty_level=uncertainty_level,
                    selected_intervention=InterventionAction.TRANSFER_CHECK.value,
                )

            evt = self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.TRANSFER_CHECKING,
                action=AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value,
                reason=args.transfer_reason,
                uncertainty_level=uncertainty_level,
                uncertainty_note=uncertainty_note,
                selected_intervention=InterventionAction.TRANSFER_CHECK.value,
                payload_json={"selected_question_id": chosen_transfer_id},
            )
            return {
                "executed_tool": tool_enum.value,
                "selected_intervention": InterventionAction.TRANSFER_CHECK.value,
                "selected_question_id": chosen_transfer_id,
                "explanation_text": None,
                "decision_event_id": evt.id,
                "knowledge_state_status": None,
            }

        if tool_enum == AgentToolName.UPDATE_KNOWLEDGE_STATE:
            try:
                args = UpdateKnowledgeStateArgs.model_validate(raw_args)
            except ValidationError as exc:
                raise IllegalAgentToolCallError(
                    f"Invalid arguments for {tool_enum.value}: {exc.errors()}"
                ) from exc

            transfer_att_id = args.transfer_attempt_id or (
                current_attempt.id
                if current_attempt.attempt_role == QuestionRole.TRANSFER_CHECK.value
                else None
            )

            # Delegate to Stage 2 LearningRepository which strictly enforces transfer_check requirement for STABLE
            ks = self.repo.update_knowledge_state(
                session_id=learning_session.id,
                topic_id=learning_session.topic_id,
                target_status=args.target_status,
                reason=args.reason,
                learner_id=learning_session.learner_id,
                unresolved_error_codes=args.unresolved_error_codes,
                transfer_attempt_id=transfer_att_id,
            )

            if args.schedule_review:
                self.repo.schedule_review_item(
                    topic_id=learning_session.topic_id,
                    session_id=learning_session.id,
                    learner_id=learning_session.learner_id,
                    trigger_reason=args.review_reason or args.reason,
                )

            if args.target_status.value == "stable":
                if diag_case.status != DiagnosticCaseStatus.RESOLVED.value:
                    if diag_case.status != DiagnosticCaseStatus.TRANSFER_CHECKING.value:
                        self.repo.transition_diagnostic_case(
                            diag_case,
                            DiagnosticCaseStatus.INTERVENTION_SELECTED,
                            action="pre_resolve_intervention",
                            reason=args.reason,
                        )
                    self.repo.transition_diagnostic_case(
                        diag_case,
                        DiagnosticCaseStatus.RESOLVED,
                        action=AgentToolName.UPDATE_KNOWLEDGE_STATE.value,
                        reason=args.reason,
                        uncertainty_level=UncertaintyLevel.LOW,
                    )
                if learning_session.status == SessionStatus.TRANSFER_CHECKING.value:
                    self.repo.transition_session_status(
                        learning_session, SessionStatus.COMPLETED
                    )

            return {
                "executed_tool": tool_enum.value,
                "selected_intervention": (
                    InterventionAction.SCHEDULE_REVIEW.value
                    if args.schedule_review
                    else None
                ),
                "selected_question_id": None,
                "explanation_text": None,
                "decision_event_id": ks.last_decision_event_id,
                "knowledge_state_status": ks.status,
            }

        if tool_enum == AgentToolName.UPSERT_HYPOTHESES:
            evt = self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
                action=AgentToolName.UPSERT_HYPOTHESES.value,
                reason=uncertainty_note or "Updated competing hypotheses; further evidence required.",
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note=uncertainty_note,
            )
            return {
                "executed_tool": tool_enum.value,
                "selected_intervention": None,
                "selected_question_id": None,
                "explanation_text": None,
                "decision_event_id": evt.id,
                "knowledge_state_status": None,
            }

        raise IllegalAgentToolCallError(
            f"Tool '{tool_enum.value}' is a read-only context tool and cannot be selected as the terminal step action."
        )
