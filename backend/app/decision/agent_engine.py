"""State-constrained Diagnostic Agent decision engine for VerbaTrail Stage 3.

Orchestrates:
1. Context gathering via whitelisted read tools (`read_material_and_question`, `query_attempts_and_evidence`)
2. Local deterministic rule pre-evaluation (`RuleEvaluator`) producing source-tracked `rule_check` evidence
3. Competing hypothesis creation & evidence linking (preserving weakened/ruled-out history)
4. Session token budget (`DIAGNOSTIC_SESSION_TOKEN_BUDGET`) and follow-up turn limit (`MAX_DIAGNOSTIC_FOLLOWUP_TURNS=2`) guards
5. Schema-constrained model decision proposal (`ModelProvider.generate_structured`) with redacted `ModelCall` audit logging
6. Graceful failure fallback (`RETRY_WAITING`) on model timeout / invalid JSON / schema errors
7. Whitelisted tool execution and Stage 2 mastery rule enforcement (`transfer_check` required for `stable`)
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.decision.heuristics import rank_followup_questions
from app.decision.schemas import (
    AgentDecisionProposal,
    AgentToolCallProposal,
    AssignPracticeArgs,
    DiagnosticStepResult,
    HypothesisUpdateProposal,
)
from app.decision.tools import AgentToolExecutor, IllegalAgentToolCallError
from app.domain.enums import (
    AgentToolName,
    AttemptEvaluationStatus,
    DiagnosticCaseStatus,
    EvidenceSourceType,
    HypothesisStatus,
    InterventionAction,
    KnowledgeMasteryStatus,
    ModelCallStatus,
    QuestionRole,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.exceptions import DomainRuleViolationError
from app.evaluation.rule_evaluator import RuleEvaluationResult, RuleEvaluator
from app.evaluation.registry import evaluator_for_domain
from app.model_provider import (
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    redact_sensitive_text,
)
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    Hypothesis,
    KnowledgeState,
    KnowledgeTopic,
    LearningSession,
    Question,
)
from app.persistence.repositories import LearningRepository

SYSTEM_PROMPT_V1 = """You are the VerbaTrail Diagnostic Agent.
You operate strictly as a domain-state-constrained decision maker, NOT a free-form chat assistant.
Rules:
1. Maintain multiple competing error hypotheses when evidence is insufficient; never force a single premature conclusion.
2. Confidence values in [0.0, 1.0] are heuristic working judgments, not calibrated probabilities.
3. Choose exactly one whitelisted action tool in `selected_tool`:
   - select_diagnostic_followup
   - provide_targeted_explanation
   - assign_targeted_practice
   - assign_transfer_verification
   - update_knowledge_state
   - upsert_hypotheses
4. Never mark KnowledgeState as 'stable' unless a 'transfer_check' attempt on the same topic has been verified correct.
Respond strictly with a JSON object matching the AgentDecisionProposal schema."""


def _map_attempt_role_to_evidence_source(role: str) -> EvidenceSourceType:
    if role == QuestionRole.DIAGNOSTIC_FOLLOWUP.value:
        return EvidenceSourceType.FOLLOWUP_RESPONSE
    if role == QuestionRole.TARGETED_PRACTICE.value:
        return EvidenceSourceType.PRACTICE_ATTEMPT
    if role == QuestionRole.TRANSFER_CHECK.value:
        return EvidenceSourceType.TRANSFER_ATTEMPT
    return EvidenceSourceType.INITIAL_ATTEMPT


class DiagnosticAgentEngine:
    """State-constrained Diagnostic Agent coordinating rules, ModelProvider, and whitelisted tools."""

    def __init__(
        self,
        session: Session,
        model_provider: ModelProvider,
        *,
        settings: Settings | None = None,
        rule_evaluator: RuleEvaluator | None = None,
    ) -> None:
        self.session = session
        self.repo = LearningRepository(session)
        self.model_provider = model_provider
        self.settings = settings or get_settings()
        self.rule_evaluator = rule_evaluator or RuleEvaluator()
        self.tool_executor = AgentToolExecutor(self.repo)

    def _serialize_hypotheses(self, diag_case: DiagnosticCase) -> list[dict[str, Any]]:
        self.session.refresh(diag_case)
        return [
            {
                "id": h.id,
                "error_code": h.error_code,
                "name": h.name,
                "heuristic_confidence": h.confidence,
                "confidence_is_heuristic": True,
                "status": h.status,
                "missing_evidence_desc": h.missing_evidence_desc,
                "evidence_count": len(h.evidence_links),
                "evidence_links": [
                    {
                        "id": ev.id,
                        "source_type": ev.source_type,
                        "source_ref": ev.source_ref,
                        "relation": ev.relation,
                        "summary": ev.summary,
                    }
                    for ev in h.evidence_links
                ],
            }
            for h in diag_case.hypotheses
        ]

    def _get_current_knowledge_state_status(
        self, learner_id: str, topic_id: str
    ) -> str | None:
        ks = self.session.scalar(
            select(KnowledgeState).where(
                KnowledgeState.learner_id == learner_id,
                KnowledgeState.topic_id == topic_id,
            )
        )
        return ks.status if ks is not None else None

    def _apply_rule_pre_evaluation(
        self,
        *,
        diag_case: DiagnosticCase,
        attempt: Attempt,
        rule_result: RuleEvaluationResult,
    ) -> None:
        """Persist local rule check candidates and source-attributed `rule_check` evidence."""
        existing_by_code: dict[str, Hypothesis] = {
            h.error_code: h for h in diag_case.hypotheses
        }

        for draft_hyp in rule_result.candidate_hypotheses:
            if draft_hyp.error_code not in existing_by_code:
                hyp = self.repo.add_hypothesis(
                    diagnostic_case_id=diag_case.id,
                    error_code=draft_hyp.error_code,
                    name=draft_hyp.name,
                    description=draft_hyp.description,
                    confidence=draft_hyp.heuristic_confidence,
                    status=draft_hyp.initial_status,
                    missing_evidence_desc=draft_hyp.missing_evidence_desc,
                )
                existing_by_code[draft_hyp.error_code] = hyp

        for draft_ev in rule_result.evidence_drafts:
            target_hyp = existing_by_code.get(draft_ev.target_error_code)
            if target_hyp is None:
                continue
            self.session.refresh(target_hyp)
            already_recorded = any(
                ev.source_ref == draft_ev.source_ref
                and ev.relation == draft_ev.relation.value
                for ev in target_hyp.evidence_links
            )
            if not already_recorded:
                self.repo.record_evidence(
                    hypothesis_id=target_hyp.id,
                    attempt_id=attempt.id,
                    source_type=draft_ev.source_type,
                    source_ref=draft_ev.source_ref,
                    relation=draft_ev.relation,
                    summary=draft_ev.summary,
                    reliability_note=draft_ev.reliability_note,
                )
        self.session.refresh(diag_case)

    def run_diagnostic_step(
        self,
        *,
        session_id: str,
        attempt_id: str,
        diagnostic_case_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> DiagnosticStepResult:
        """Execute one complete, state-validated diagnostic step on a learner Attempt."""
        learning_session = self.session.get(LearningSession, session_id)
        if learning_session is None:
            raise DomainRuleViolationError(f"Unknown LearningSession ID: {session_id}")

        attempt = self.session.get(Attempt, attempt_id)
        if attempt is None or attempt.session_id != session_id:
            raise DomainRuleViolationError(
                f"Attempt {attempt_id} does not exist or does not belong to session {session_id}."
            )

        question = self.session.get(Question, attempt.question_id)
        topic = self.session.get(KnowledgeTopic, learning_session.topic_id)
        if question is None or topic is None:
            raise DomainRuleViolationError("Session topic or attempt question is missing.")

        # Idempotency check: if a DecisionEvent with this idempotency_key already exists, replay state
        if idempotency_key:
            existing_evt = self.session.scalar(
                select(DecisionEvent).where(
                    DecisionEvent.idempotency_key == idempotency_key
                )
            )
            if existing_evt is not None and existing_evt.diagnostic_case_id:
                existing_case = self.session.get(
                    DiagnosticCase, existing_evt.diagnostic_case_id
                )
                if existing_case is not None:
                    payload = existing_evt.payload_json or {}
                    return DiagnosticStepResult(
                        session_id=learning_session.id,
                        diagnostic_case_id=existing_case.id,
                        attempt_id=attempt.id,
                        case_status=DiagnosticCaseStatus(existing_case.status),
                        executed_tool=str(
                            payload.get("executed_tool", existing_evt.action)
                        ),
                        selected_intervention=existing_case.selected_intervention,
                        selected_question_id=payload.get("selected_question_id"),
                        explanation_text=payload.get("explanation_text"),
                        uncertainty_level=UncertaintyLevel(
                            existing_evt.uncertainty_level
                        ),
                        uncertainty_note=existing_case.uncertainty_note,
                        confidence_is_heuristic=True,
                        followup_turns_used=self.repo.get_case_followup_turn_count(
                            existing_case.id
                        ),
                        max_followup_turns=self.settings.max_diagnostic_followup_turns,
                        tokens_used_in_case=self.repo.get_case_token_usage(
                            existing_case.id
                        ),
                        session_token_budget=self.settings.diagnostic_session_token_budget,
                        degraded_mode=bool(payload.get("degraded_mode", False)),
                        degradation_reason=payload.get("degradation_reason"),
                        decision_event_id=existing_evt.id,
                        hypotheses_snapshot=self._serialize_hypotheses(existing_case),
                        knowledge_state_status=self._get_current_knowledge_state_status(
                            learning_session.learner_id, learning_session.topic_id
                        ),
                    )

        # Resolve or create DiagnosticCase
        diag_case: DiagnosticCase | None = None
        if diagnostic_case_id is not None:
            diag_case = self.session.get(DiagnosticCase, diagnostic_case_id)
            if diag_case is None or diag_case.session_id != session_id:
                raise DomainRuleViolationError(
                    f"DiagnosticCase {diagnostic_case_id} not found for session {session_id}."
                )
        else:
            diag_case = self.repo.create_diagnostic_case(
                session_id=session_id,
                trigger_attempt_id=attempt.id,
            )

        # Step 1: Run local deterministic rule pre-evaluation
        rule_result = evaluator_for_domain(topic.domain_code).evaluate_attempt(
            attempt=attempt,
            question=question,
            topic=topic,
        )

        if attempt.evaluation_status != AttemptEvaluationStatus.EVALUATED.value:
            attempt.is_correct = rule_result.answer_matches_standard
            attempt.evaluation_status = AttemptEvaluationStatus.EVALUATED.value
            attempt.evaluation_summary = rule_result.summary
            self.session.flush()

        if diag_case.status == DiagnosticCaseStatus.COLLECTING_ATTEMPT.value:
            self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.INITIAL_EVALUATED,
                action="rule_pre_evaluation",
                reason=rule_result.summary,
                uncertainty_level=UncertaintyLevel.MEDIUM,
            )

        self._apply_rule_pre_evaluation(
            diag_case=diag_case,
            attempt=attempt,
            rule_result=rule_result,
        )

        if diag_case.status == DiagnosticCaseStatus.INITIAL_EVALUATED.value:
            self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.HYPOTHESES_GENERATED,
                action="initialize_competing_hypotheses",
                reason=f"Rule pre-evaluator prepared {len(diag_case.hypotheses)} competing hypotheses.",
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            )

        # Step 2: Gather context via whitelisted read tools
        material_context = self.tool_executor.read_material_and_question(
            topic_id=topic.id,
            question_id=question.id,
        )
        history_context = self.tool_executor.query_attempts_and_evidence(
            learning_session=learning_session,
            diag_case=diag_case,
        )

        followup_turns_used = self.repo.get_case_followup_turn_count(diag_case.id)
        max_followup_turns = self.settings.max_diagnostic_followup_turns
        tokens_used_so_far = self.repo.get_case_token_usage(diag_case.id)
        session_token_budget = self.settings.diagnostic_session_token_budget

        # Step 3: Check session token budget with pre-call reservation guard
        # A single schema-constrained model call typically requires at least 256 tokens (prompt + JSON completion).
        # We enforce a pre-call reservation threshold so that calls are not made when remaining budget is too low.
        MIN_RESERVED_TOKENS_PER_CALL = 256
        remaining_budget = session_token_budget - tokens_used_so_far
        if tokens_used_so_far >= session_token_budget or remaining_budget < MIN_RESERVED_TOKENS_PER_CALL:
            degrade_reason = (
                f"诊断案例已消耗 {tokens_used_so_far} tokens，剩余额度 ({max(0, remaining_budget)} tokens) "
                f"低于单次调用最小预留安全阈值 ({MIN_RESERVED_TOKENS_PER_CALL} tokens，预算上限 {session_token_budget})；"
                "事前拦截远程模型调用，保留候选假设不确定性并安全转入待复习与针对性练习。"
            )
            self.repo.record_model_call(
                provider_name=self.model_provider.provider_name,
                model_name=self.model_provider.model_name,
                prompt_version="diag_agent_v1",
                status=ModelCallStatus.BUDGET_EXCEEDED,
                redacted_summary=degrade_reason,
                error_code="MODEL_TOKEN_BUDGET_EXCEEDED",
                session_id=learning_session.id,
                diagnostic_case_id=diag_case.id,
            )
            self.repo.schedule_review_item(
                topic_id=topic.id,
                session_id=learning_session.id,
                learner_id=learning_session.learner_id,
                trigger_reason=degrade_reason,
            )
            evt = self.repo.transition_diagnostic_case(
                diag_case,
                DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE,
                action="budget_limit_degrade",
                reason=degrade_reason,
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note=degrade_reason,
                selected_intervention=InterventionAction.SCHEDULE_REVIEW.value,
                payload_json={
                    "executed_tool": "budget_limit_degrade",
                    "degraded_mode": True,
                    "degradation_reason": degrade_reason,
                },
            )
            if idempotency_key:
                evt.idempotency_key = idempotency_key
                self.session.flush()

            return DiagnosticStepResult(
                session_id=learning_session.id,
                diagnostic_case_id=diag_case.id,
                attempt_id=attempt.id,
                case_status=DiagnosticCaseStatus(diag_case.status),
                executed_tool="budget_limit_degrade",
                selected_intervention=InterventionAction.SCHEDULE_REVIEW.value,
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note=degrade_reason,
                confidence_is_heuristic=True,
                followup_turns_used=followup_turns_used,
                max_followup_turns=max_followup_turns,
                tokens_used_in_case=tokens_used_so_far,
                session_token_budget=session_token_budget,
                degraded_mode=True,
                degradation_reason=degrade_reason,
                decision_event_id=evt.id,
                hypotheses_snapshot=self._serialize_hypotheses(diag_case),
                knowledge_state_status=self._get_current_knowledge_state_status(
                    learning_session.learner_id, learning_session.topic_id
                ),
            )

        # Step 4: Invoke ModelProvider for structured Agent decision proposal
        available_questions = {
            role.value: [
                {"id": q.id, "prompt_text": q.prompt_text}
                for q in self.repo.list_questions_for_topic(topic.id, role=role)
            ]
            for role in QuestionRole
        }
        user_prompt_payload = {
            "material_and_question": material_context,
            "history_and_evidence": history_context,
            "rule_pre_evaluation": {
                "answer_matches_standard": rule_result.answer_matches_standard,
                "has_reasoning_or_trace": rule_result.has_reasoning_or_trace,
                "summary": rule_result.summary,
            },
            "available_questions_by_role": available_questions,
            "constraints": {
                "followup_turns_used": followup_turns_used,
                "max_followup_turns": max_followup_turns,
                "remaining_token_budget": session_token_budget - tokens_used_so_far,
            },
        }

        serialized_payload = json.dumps(user_prompt_payload, ensure_ascii=False)
        # Conservative prompt token estimation (characters // 3 for bilingual JSON prompt)
        estimated_prompt_tokens = max(
            128,
            (len(SYSTEM_PROMPT_V1) + len(serialized_payload)) // 3,
        )
        # Dynamically clamp completion max_tokens to prevent large overshoots
        safe_completion_budget = max(64, remaining_budget - estimated_prompt_tokens)

        model_request = ModelRequest(
            prompt_version="diag_agent_v1",
            system_prompt=SYSTEM_PROMPT_V1,
            user_prompt=serialized_payload,
            max_tokens=min(
                self.settings.model_max_tokens_per_call,
                safe_completion_budget,
            ),
            temperature=self.settings.model_temperature,
            session_id=learning_session.id,
            diagnostic_case_id=diag_case.id,
            metadata={"attempt_id": attempt.id, "question_role": attempt.attempt_role, "domain_code": topic.domain_code},
        )

        try:
            model_resp = self.model_provider.generate_structured(
                model_request, AgentDecisionProposal
            )
            self.repo.record_model_call(
                provider_name=model_resp.provider_name,
                model_name=model_resp.model_name,
                prompt_version=model_resp.prompt_version,
                status=ModelCallStatus.SUCCEEDED,
                redacted_summary=model_resp.redacted_summary,
                latency_ms=model_resp.latency_ms,
                prompt_tokens=model_resp.usage.prompt_tokens,
                completion_tokens=model_resp.usage.completion_tokens,
                total_tokens=model_resp.usage.total_tokens,
                attempt_count=model_resp.attempt_count,
                session_id=learning_session.id,
                diagnostic_case_id=diag_case.id,
            )
        except ModelProviderError as exc:
            # Failure recovery: preserve Attempt & existing Evidence, enter RETRY_WAITING
            self.repo.record_model_call(
                provider_name=self.model_provider.provider_name,
                model_name=self.model_provider.model_name,
                prompt_version=model_request.prompt_version,
                status=exc.status,
                redacted_summary=redact_sensitive_text(
                    f"Model call failed ({exc.error_code}): {exc.redacted_message}"
                ),
                latency_ms=exc.latency_ms,
                attempt_count=exc.attempt_count,
                error_code=exc.error_code,
                session_id=learning_session.id,
                diagnostic_case_id=diag_case.id,
            )
            fallback_note = (
                f"模型调用未成功 ({exc.error_code})，已完整保留作答与规则证据，进入等待重试状态。"
            )
            diag_case.status = DiagnosticCaseStatus.RETRY_WAITING.value
            diag_case.uncertainty_note = fallback_note
            evt = self.repo.append_decision_event(
                session_id=learning_session.id,
                diagnostic_case_id=diag_case.id,
                event_type="model_call_failed_fallback",
                from_state=DiagnosticCaseStatus.HYPOTHESES_GENERATED.value,
                to_state=DiagnosticCaseStatus.RETRY_WAITING.value,
                action="enter_retry_waiting",
                reason=fallback_note,
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                payload_json={
                    "error_code": exc.error_code,
                    "executed_tool": "enter_retry_waiting",
                    "degraded_mode": True,
                    "degradation_reason": fallback_note,
                },
                idempotency_key=idempotency_key,
            )
            return DiagnosticStepResult(
                session_id=learning_session.id,
                diagnostic_case_id=diag_case.id,
                attempt_id=attempt.id,
                case_status=DiagnosticCaseStatus.RETRY_WAITING,
                executed_tool="enter_retry_waiting",
                selected_intervention=None,
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note=fallback_note,
                confidence_is_heuristic=True,
                followup_turns_used=followup_turns_used,
                max_followup_turns=max_followup_turns,
                tokens_used_in_case=self.repo.get_case_token_usage(diag_case.id),
                session_token_budget=session_token_budget,
                degraded_mode=True,
                degradation_reason=fallback_note,
                decision_event_id=evt.id,
                hypotheses_snapshot=self._serialize_hypotheses(diag_case),
                knowledge_state_status=self._get_current_knowledge_state_status(
                    learning_session.learner_id, learning_session.topic_id
                ),
            )

        proposal = model_resp.parsed_output

        # Step 5: Apply competing hypothesis updates & evidence links
        if proposal.hypothesis_updates:
            self.tool_executor.upsert_hypotheses(
                diag_case=diag_case,
                trigger_attempt=attempt,
                proposals=proposal.hypothesis_updates,
                source_type=_map_attempt_role_to_evidence_source(attempt.attempt_role),
                decision_reason=proposal.reasoning,
            )
            if diag_case.status in (
                DiagnosticCaseStatus.QUESTION_SELECTED.value,
                DiagnosticCaseStatus.NEEDS_EVIDENCE.value,
                DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE.value,
            ):
                self.repo.transition_diagnostic_case(
                    diag_case,
                    DiagnosticCaseStatus.HYPOTHESES_UPDATED,
                    action="apply_new_evidence_to_hypotheses",
                    reason=proposal.reasoning,
                    uncertainty_level=proposal.uncertainty_level,
                    uncertainty_note=proposal.uncertainty_note,
                )

        # Step 6: Enforce MAX_DIAGNOSTIC_FOLLOWUP_TURNS limit if model wants another follow-up
        chosen_tool_proposal = proposal.selected_tool
        degraded_mode = False
        degradation_reason: str | None = None

        if (
            chosen_tool_proposal.tool_name
            == AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value
            and followup_turns_used >= max_followup_turns
        ):
            degraded_mode = True
            degradation_reason = (
                f"已达到最大诊断追问轮数上限 (MAX_DIAGNOSTIC_FOLLOWUP_TURNS={max_followup_turns})，"
                "候选错误假设仍存在不确定性，不强行认定掌握，自动降级为针对性练习并加入复习队列。"
            )
            # Mark any remaining candidate hypotheses as insufficient_evidence rather than confirmed/ruled_out
            for h in diag_case.hypotheses:
                if h.status == HypothesisStatus.CANDIDATE.value:
                    self.repo.update_hypothesis(
                        h,
                        new_status=HypothesisStatus.INSUFFICIENT_EVIDENCE,
                        new_confidence=h.confidence,
                        reason=degradation_reason,
                    )
            self.repo.schedule_review_item(
                topic_id=topic.id,
                session_id=learning_session.id,
                learner_id=learning_session.learner_id,
                trigger_reason=degradation_reason,
            )
            active_codes = [
                h.error_code
                for h in diag_case.hypotheses
                if h.status != HypothesisStatus.RULED_OUT.value
            ]
            chosen_tool_proposal = AgentToolCallProposal(
                tool_name=AgentToolName.ASSIGN_TARGETED_PRACTICE.value,
                arguments=AssignPracticeArgs(
                    target_error_codes=active_codes,
                    practice_reason=degradation_reason,
                ).model_dump(),
            )

        # Step 7: Validate & execute whitelisted action tool
        try:
            action_outcome = self.tool_executor.execute_action_tool(
                learning_session=learning_session,
                diag_case=diag_case,
                current_attempt=attempt,
                tool_proposal=chosen_tool_proposal,
                uncertainty_level=(
                    UncertaintyLevel.INSUFFICIENT_EVIDENCE
                    if degraded_mode
                    else proposal.uncertainty_level
                ),
                uncertainty_note=degradation_reason or proposal.uncertainty_note,
            )
            if action_outcome.get("degraded_mode"):
                degraded_mode = True
                degradation_reason = degradation_reason or action_outcome.get(
                    "degradation_reason"
                )
        except (IllegalAgentToolCallError, DomainRuleViolationError) as exc:
            # Record rejected tool call in DecisionEvent before re-raising
            self.repo.append_decision_event(
                session_id=learning_session.id,
                diagnostic_case_id=diag_case.id,
                event_type="illegal_agent_action_blocked",
                from_state=diag_case.status,
                to_state=diag_case.status,
                action=chosen_tool_proposal.tool_name,
                reason=f"Blocked illegal or domain-violating Agent action: {exc}",
                uncertainty_level=UncertaintyLevel.HIGH,
                payload_json={
                    "rejected_tool": chosen_tool_proposal.tool_name,
                    "rejected_arguments": chosen_tool_proposal.arguments,
                    "error": str(exc),
                },
            )
            raise

        # Bind idempotency_key to the terminal DecisionEvent if provided
        terminal_evt = self.session.get(
            DecisionEvent, action_outcome["decision_event_id"]
        )
        if terminal_evt is not None:
            merged_payload = dict(terminal_evt.payload_json or {})
            merged_payload.update(
                {
                    "executed_tool": action_outcome["executed_tool"],
                    "selected_question_id": action_outcome["selected_question_id"],
                    "explanation_text": action_outcome["explanation_text"],
                    "degraded_mode": degraded_mode,
                    "degradation_reason": degradation_reason,
                }
            )
            # If idempotency_key is needed and terminal_evt was just created, record an idempotency index event
            if idempotency_key and terminal_evt.idempotency_key is None:
                idem_evt = self.repo.append_decision_event(
                    session_id=learning_session.id,
                    diagnostic_case_id=diag_case.id,
                    event_type="diagnostic_step_completed",
                    from_state=diag_case.status,
                    to_state=diag_case.status,
                    action=action_outcome["executed_tool"],
                    reason=degradation_reason or proposal.reasoning,
                    uncertainty_level=(
                        UncertaintyLevel.INSUFFICIENT_EVIDENCE
                        if degraded_mode
                        else proposal.uncertainty_level
                    ),
                    payload_json=merged_payload,
                    idempotency_key=idempotency_key,
                )
                decision_event_id = idem_evt.id
            else:
                decision_event_id = terminal_evt.id
        else:
            decision_event_id = action_outcome["decision_event_id"]

        updated_followup_turns = self.repo.get_case_followup_turn_count(diag_case.id)
        updated_tokens_used = self.repo.get_case_token_usage(diag_case.id)

        return DiagnosticStepResult(
            session_id=learning_session.id,
            diagnostic_case_id=diag_case.id,
            attempt_id=attempt.id,
            case_status=DiagnosticCaseStatus(diag_case.status),
            executed_tool=action_outcome["executed_tool"],
            selected_intervention=action_outcome["selected_intervention"],
            selected_question_id=action_outcome["selected_question_id"],
            explanation_text=action_outcome["explanation_text"],
            uncertainty_level=(
                UncertaintyLevel.INSUFFICIENT_EVIDENCE
                if degraded_mode
                else proposal.uncertainty_level
            ),
            uncertainty_note=degradation_reason or proposal.uncertainty_note,
            confidence_is_heuristic=True,
            followup_turns_used=updated_followup_turns,
            max_followup_turns=max_followup_turns,
            tokens_used_in_case=updated_tokens_used,
            session_token_budget=session_token_budget,
            degraded_mode=degraded_mode,
            degradation_reason=degradation_reason,
            decision_event_id=decision_event_id,
            hypotheses_snapshot=self._serialize_hypotheses(diag_case),
            knowledge_state_status=action_outcome["knowledge_state_status"]
            or self._get_current_knowledge_state_status(
                learning_session.learner_id, learning_session.topic_id
            ),
        )
