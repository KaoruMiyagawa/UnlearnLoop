"""Stage 3 automated tests for ModelProvider, RuleEvaluator, and DiagnosticAgentEngine.

All tests run 100% offline without external network access or real API keys.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.decision import (
    AgentDecisionProposal,
    AgentToolCallProposal,
    DiagnosticAgentEngine,
    HypothesisEvidenceProposal,
    HypothesisUpdateProposal,
    IllegalAgentToolCallError,
)
from app.domain.enums import (
    AgentToolName,
    DiagnosticCaseStatus,
    EvidenceRelation,
    HypothesisStatus,
    InterventionAction,
    KnowledgeMasteryStatus,
    ModelCallStatus,
    QuestionRole,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.exceptions import UnverifiedMasteryError
from app.model_provider import (
    DeepSeekProvider,
    FakeModelProvider,
    ModelAuthenticationError,
    ModelInvalidJSONError,
    ModelRequest,
    ModelTimeoutError,
    RemoteModelCallsDisabledError,
    TokenUsage,
    redact_sensitive_text,
)
from app.persistence.database import transactional_session
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    Hypothesis,
    KnowledgeState,
    LearningSession,
    ModelCall,
    ReviewItem,
)
from app.persistence.repositories import LearningRepository
from app.persistence.seed import import_content_pack


def test_end_to_end_multistep_diagnostic_loop_with_competing_hypotheses_and_transfer_check(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """End-to-end 5-step diagnostic loop:
    1. Initial attempt ('3' without trace) -> Rule pre-eval + 2 competing hypotheses -> Follow-up 1
    2. Follow-up attempt ('依次打印 1、3') -> Contradicts memorized-only, supports range_start_at_one -> Targeted practice
    3. Practice attempt ('6') -> Assign transfer verification
    4. Transfer attempt 1 ('3 15', wrong) -> Keep needs_practice + schedule review
    5. Transfer attempt 2 ('3 17', correct) -> Verified transfer -> Update KnowledgeState to STABLE
    """
    fake_provider = FakeModelProvider(
        scripted_steps=[
            # Step 1: After initial attempt "3" (bare output), keep 2 competing hypotheses & ask follow-up
            AgentDecisionProposal(
                reasoning="学习者仅输出最终结果 3，无法区分“心算正确但未写过程”与“误以为 range(3) 是 1,2 碰巧相加得 3”，选择区分性追问。",
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note="两个竞争性错误假设并存，需通过循环内打印序列区分。",
                hypothesis_updates=[
                    HypothesisUpdateProposal(
                        error_code="loop_memorized_result_without_trace",
                        heuristic_confidence=0.48,
                        status=HypothesisStatus.INSUFFICIENT_EVIDENCE,
                        missing_evidence_desc="需确认每一轮循环体内 total 的打印序列",
                        evidence_items=[
                            HypothesisEvidenceProposal(
                                relation=EvidenceRelation.SUPPORTS,
                                summary="初始作答仅给出数字 3，无中间状态描述。",
                            )
                        ],
                    ),
                    HypothesisUpdateProposal(
                        error_code="range_start_at_one",
                        name="误以为 range(3) 生成 [1, 2]",
                        description="认为 range(3) 从 1 开始到 2 结束，1+2 碰巧等于 3。",
                        heuristic_confidence=0.38,
                        status=HypothesisStatus.CANDIDATE,
                        missing_evidence_desc="需检验第 1 轮循环输出是 0 还是 1",
                        evidence_items=[
                            HypothesisEvidenceProposal(
                                relation=EvidenceRelation.NEUTRAL,
                                summary="单一输出 3 与 0+1+2 及 1+2 均兼容。",
                            )
                        ],
                    ),
                ],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
                    arguments={
                        "followup_question_id": "q_py_loop_followup_01",
                        "target_error_codes": [
                            "loop_memorized_result_without_trace",
                            "range_start_at_one",
                        ],
                        "discriminating_reason": "询问每轮循环体内的打印值，若首轮为 1 则确诊 range 起点误解。",
                    },
                ),
            ),
            # Step 2: Learner answers follow-up with "1、3" -> confirms range_start_at_one, lowers memorized_only
            AgentDecisionProposal(
                reasoning="追问回应为 '1、3'，表明学习者能够追踪循环累加，但误认为 range(3) 从 1 开始生成 1 和 2。降低未追踪假设，确认 range 起点误解，安排针对性练习。",
                uncertainty_level=UncertaintyLevel.LOW,
                uncertainty_note="已通过区分性追问定位到 range 起点与循环赋值卡点。",
                hypothesis_updates=[
                    HypothesisUpdateProposal(
                        error_code="loop_memorized_result_without_trace",
                        heuristic_confidence=0.15,
                        status=HypothesisStatus.LOWERED,
                        missing_evidence_desc="已证实能逐步追踪累加，但输入序列有误",
                        evidence_items=[
                            HypothesisEvidenceProposal(
                                relation=EvidenceRelation.CONTRADICTS,
                                summary="追问中能按轮次写出累加过程（1 -> 3），排除完全不追踪状态的假设。",
                            )
                        ],
                    ),
                    HypothesisUpdateProposal(
                        error_code="range_start_at_one",
                        heuristic_confidence=0.86,
                        status=HypothesisStatus.CONFIRMED,
                        missing_evidence_desc="无",
                        evidence_items=[
                            HypothesisEvidenceProposal(
                                relation=EvidenceRelation.SUPPORTS,
                                summary="追问第一轮输出写为 1 且仅两轮（1、3），证实将 range(3) 误作 [1, 2]。",
                            )
                        ],
                    ),
                ],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.ASSIGN_TARGETED_PRACTICE.value,
                    arguments={
                        "practice_question_id": "q_py_loop_practice_01",
                        "target_error_codes": ["range_start_at_one"],
                        "practice_reason": "通过显式起止范围 range(1, 4) 的循环练习巩固边界与状态更新。",
                    },
                ),
            ),
            # Step 3: Learner answers practice question correctly ("6") -> move to transfer verification
            AgentDecisionProposal(
                reasoning="针对性练习作答正确（输出 6），但练习题答对不等于真正掌握，必须安排迁移验证题检验独立应用。",
                uncertainty_level=UncertaintyLevel.MEDIUM,
                uncertainty_note="练习通过，等待变式迁移验证。",
                hypothesis_updates=[
                    HypothesisUpdateProposal(
                        error_code="range_start_at_one",
                        heuristic_confidence=0.35,
                        status=HypothesisStatus.LOWERED,
                        evidence_items=[
                            HypothesisEvidenceProposal(
                                relation=EvidenceRelation.CONTRADICTS,
                                summary="针对性练习正确追踪了 range(1, 4) 的最后一轮 i=3。",
                            )
                        ],
                    )
                ],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value,
                    arguments={
                        "transfer_question_id": "q_py_loop_transfer_01",
                        "transfer_reason": "在双变量（count 与 running_sum）新场景中验证循环与 range 迁移能力。",
                    },
                ),
            ),
            # Step 4: Learner fails first transfer check ("3 15") -> keep needs_practice & schedule review
            AgentDecisionProposal(
                reasoning="迁移验证题回答 '3 15'（正确应为 '3 17'），说明在多变量累加时仍遗漏了初始值或某轮步长，更新状态为 needs_practice 并安排复习。",
                uncertainty_level=UncertaintyLevel.MEDIUM,
                uncertainty_note="迁移验证未通过，尚不能标记为 stable。",
                hypothesis_updates=[],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.UPDATE_KNOWLEDGE_STATE.value,
                    arguments={
                        "target_status": KnowledgeMasteryStatus.NEEDS_PRACTICE.value,
                        "reason": "迁移验证题 q_py_loop_transfer_01 作答为 '3 15' 未通过，需继续练习与复习。",
                        "unresolved_error_codes": ["range_start_at_one"],
                        "schedule_review": True,
                        "review_reason": "最近一次迁移验证失败（多变量循环状态追踪偏差）。",
                    },
                ),
            ),
            # Step 5: After reviewing, Agent assigns a fresh, unattempted transfer question with different context
            AgentDecisionProposal(
                reasoning="首次迁移验证失败后不允许重试原题认定掌握，必须通过不同情境的独立迁移题 q_py_loop_transfer_02 验证独立应用。",
                uncertainty_level=UncertaintyLevel.MEDIUM,
                uncertainty_note="分配独立新情境迁移题。",
                hypothesis_updates=[],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value,
                    arguments={
                        "transfer_question_id": "q_py_loop_transfer_02",
                        "transfer_reason": "在签到奖励累加场景中检验循环状态迁移能力。",
                    },
                ),
            ),
            # Step 6: Learner passes the fresh transfer check ("3 60") -> update KnowledgeState to STABLE
            AgentDecisionProposal(
                reasoning="学习者独立完成全新情境迁移验证题 q_py_loop_transfer_02 并正确输出 '3 60'，证据链完整，允许将知识状态更新为 stable。",
                uncertainty_level=UncertaintyLevel.LOW,
                uncertainty_note="独立新情境迁移验证已通过。",
                hypothesis_updates=[
                    HypothesisUpdateProposal(
                        error_code="range_start_at_one",
                        heuristic_confidence=0.05,
                        status=HypothesisStatus.RULED_OUT,
                        evidence_items=[
                            HypothesisEvidenceProposal(
                                relation=EvidenceRelation.CONTRADICTS,
                                summary="全新情境迁移验证题 q_py_loop_transfer_02 准确完成 range(3) 共 3 轮连续累加。",
                            )
                        ],
                    )
                ],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.UPDATE_KNOWLEDGE_STATE.value,
                    arguments={
                        "target_status": KnowledgeMasteryStatus.STABLE.value,
                        "reason": "成功通过独立新情境迁移验证题 q_py_loop_transfer_02。",
                        "unresolved_error_codes": [],
                        "schedule_review": False,
                    },
                ),
            ),
        ]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=test_settings
        )

        topic = repo.get_topic_by_slug("py-for-loop")
        assert topic is not None
        learning_session = repo.create_session(
            topic_id=topic.id,
            current_question_id="q_py_loop_initial_01",
        )

        # --- Turn 1: Initial Attempt ("3") ---
        att_1 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_loop_initial_01",
            submitted_answer="3",
        )
        step_1 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_1.id,
        )
        assert step_1.case_status == DiagnosticCaseStatus.QUESTION_SELECTED
        assert step_1.executed_tool == AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value
        assert step_1.selected_question_id == "q_py_loop_followup_01"
        assert step_1.followup_turns_used == 1
        assert len(step_1.hypotheses_snapshot) >= 2

        diag_case_id = step_1.diagnostic_case_id

        # --- Turn 2: Follow-up Attempt ("1、3") ---
        att_2 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_loop_followup_01",
            submitted_answer="1、3",
        )
        step_2 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_2.id,
            diagnostic_case_id=diag_case_id,
        )
        assert step_2.case_status == DiagnosticCaseStatus.INTERVENTION_SELECTED
        assert step_2.executed_tool == AgentToolName.ASSIGN_TARGETED_PRACTICE.value
        assert step_2.selected_question_id == "q_py_loop_practice_01"

        hyp_by_code = {h["error_code"]: h for h in step_2.hypotheses_snapshot}
        assert hyp_by_code["loop_memorized_result_without_trace"]["status"] == "lowered"
        assert hyp_by_code["range_start_at_one"]["status"] == "confirmed"

        # --- Turn 3: Targeted Practice Attempt ("6") ---
        att_3 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_loop_practice_01",
            submitted_answer="6",
        )
        step_3 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_3.id,
            diagnostic_case_id=diag_case_id,
        )
        assert step_3.case_status == DiagnosticCaseStatus.TRANSFER_CHECKING
        assert step_3.executed_tool == AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value
        assert step_3.selected_question_id == "q_py_loop_transfer_01"

        # --- Turn 4: Failed Transfer Attempt on q_py_loop_transfer_01 ("3 15") ---
        att_4_fail = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_loop_transfer_01",
            submitted_answer="3 15",
        )
        step_4 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_4_fail.id,
            diagnostic_case_id=diag_case_id,
        )
        assert step_4.knowledge_state_status == KnowledgeMasteryStatus.NEEDS_PRACTICE.value

        # --- Turn 5: Agent assigns fresh transfer check question q_py_loop_transfer_02 ---
        step_5 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_4_fail.id,
            diagnostic_case_id=diag_case_id,
        )
        assert step_5.case_status == DiagnosticCaseStatus.TRANSFER_CHECKING
        assert step_5.executed_tool == AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value
        assert step_5.selected_question_id == "q_py_loop_transfer_02"

        # --- Turn 6: Passed fresh transfer check on q_py_loop_transfer_02 ("3 60") ---
        att_6_pass = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_loop_transfer_02",
            submitted_answer="3 60",
        )
        step_6 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_6_pass.id,
            diagnostic_case_id=diag_case_id,
        )
        assert step_6.case_status == DiagnosticCaseStatus.RESOLVED
        assert step_6.knowledge_state_status == KnowledgeMasteryStatus.STABLE.value
        assert step_6.tokens_used_in_case == 1800  # 6 calls * 300 tokens

        # Verify historical records are all preserved (nothing overwritten or deleted)
        all_attempts = list(
            session.scalars(
                select(Attempt).where(Attempt.session_id == learning_session.id)
            ).all()
        )
        all_events = list(
            session.scalars(
                select(DecisionEvent).where(
                    DecisionEvent.session_id == learning_session.id
                )
            ).all()
        )
        all_model_calls = list(
            session.scalars(
                select(ModelCall).where(
                    ModelCall.diagnostic_case_id == diag_case_id
                )
            ).all()
        )
        all_reviews = list(
            session.scalars(
                select(ReviewItem).where(
                    ReviewItem.session_id == learning_session.id
                )
            ).all()
        )
        assert len(all_attempts) == 5
        assert len(all_events) >= 8
        assert len(all_model_calls) == 6
        assert len(all_reviews) == 1


def test_followup_turn_limit_enforced_and_degrades_without_false_mastery(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify MAX_DIAGNOSTIC_FOLLOWUP_TURNS=2 blocks a 3rd follow-up and degrades safely."""
    follow_up_proposal = AgentDecisionProposal(
        reasoning="仍需更多证据区分候选假设，继续追问。",
        uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
        uncertainty_note="证据仍不充分。",
        hypothesis_updates=[
            HypothesisUpdateProposal(
                error_code="var_assign_reactive_formula",
                heuristic_confidence=0.52,
                status=HypothesisStatus.CANDIDATE,
            )
        ],
        selected_tool=AgentToolCallProposal(
            tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
            arguments={
                "discriminating_reason": "继续请求诊断追问。",
            },
        ),
    )
    # Enqueue 3 identical follow-up requests
    fake_provider = FakeModelProvider(
        scripted_steps=[follow_up_proposal, follow_up_proposal, follow_up_proposal]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=test_settings
        )

        topic = repo.get_topic_by_slug("py-variable-assignment")
        assert topic is not None
        learning_session = repo.create_session(
            topic_id=topic.id,
            current_question_id="q_py_var_initial_01",
        )

        # Follow-up Turn 1 (allowed, 0 < 2)
        att_1 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_var_initial_01",
            submitted_answer="20 25",
        )
        res_1 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_1.id,
        )
        assert res_1.executed_tool == AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value
        assert res_1.followup_turns_used == 1
        assert res_1.degraded_mode is False

        # Follow-up Turn 2 (allowed, 1 < 2)
        att_2 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_var_followup_01",
            submitted_answer="不太确定",
        )
        res_2 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_2.id,
            diagnostic_case_id=res_1.diagnostic_case_id,
        )
        assert res_2.executed_tool == AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value
        assert res_2.followup_turns_used == 2
        assert res_2.degraded_mode is False

        # Follow-up Turn 3 (blocked by MAX_DIAGNOSTIC_FOLLOWUP_TURNS=2! Degrades to targeted_practice + review)
        att_3 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_var_followup_01",
            submitted_answer="还是不确定",
        )
        res_3 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_3.id,
            diagnostic_case_id=res_1.diagnostic_case_id,
        )
        assert res_3.degraded_mode is True
        assert res_3.executed_tool == AgentToolName.ASSIGN_TARGETED_PRACTICE.value
        assert res_3.selected_intervention == InterventionAction.TARGETED_PRACTICE.value
        assert res_3.uncertainty_level == UncertaintyLevel.INSUFFICIENT_EVIDENCE
        assert res_3.knowledge_state_status != KnowledgeMasteryStatus.STABLE.value

        # Candidate hypotheses were transitioned to insufficient_evidence rather than falsely resolved
        statuses = {h["status"] for h in res_3.hypotheses_snapshot}
        assert HypothesisStatus.INSUFFICIENT_EVIDENCE.value in statuses


def test_session_token_budget_limit_degrades_safely_without_calling_model(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify reaching DIAGNOSTIC_SESSION_TOKEN_BUDGET degrades safely without calling model or claiming mastery."""
    tight_budget_settings = test_settings.model_copy(
        update={"diagnostic_session_token_budget": 500}
    )
    step_1_proposal = AgentDecisionProposal(
        reasoning="初次诊断追问。",
        uncertainty_level=UncertaintyLevel.MEDIUM,
        selected_tool=AgentToolCallProposal(
            tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
            arguments={"discriminating_reason": "追问边界。"},
        ),
    )
    fake_provider = FakeModelProvider(
        scripted_steps=[
            (
                step_1_proposal,
                TokenUsage(prompt_tokens=300, completion_tokens=250, total_tokens=550),
            )
        ]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=tight_budget_settings
        )

        topic = repo.get_topic_by_slug("py-range-function")
        assert topic is not None
        learning_session = repo.create_session(
            topic_id=topic.id,
            current_question_id="q_py_range_initial_01",
        )

        att_1 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_range_initial_01",
            submitted_answer="[1, 2, 3, 4, 5]",
        )
        res_1 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_1.id,
        )
        assert res_1.tokens_used_in_case == 550

        # Second step exceeds the 500-token budget before calling the model
        att_2 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_range_followup_01",
            submitted_answer="[1, 2, 3]",
        )
        res_2 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_2.id,
            diagnostic_case_id=res_1.diagnostic_case_id,
        )
        assert res_2.degraded_mode is True
        assert res_2.executed_tool == "budget_limit_degrade"
        assert res_2.case_status == DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE
        assert len(fake_provider.recorded_requests) == 1  # Model was NOT called on step 2


def test_illegal_tool_call_and_premature_stable_mastery_are_blocked(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify unauthorized tool names and unverified STABLE mastery updates are intercepted."""
    fake_provider = FakeModelProvider(
        scripted_steps=[
            # 1. Model attempts to call an arbitrary non-whitelisted tool
            AgentDecisionProposal(
                reasoning="Attempt unauthorized shell execution.",
                uncertainty_level=UncertaintyLevel.LOW,
                selected_tool=AgentToolCallProposal(
                    tool_name="execute_arbitrary_shell_command",
                    arguments={"cmd": "rm -rf /"},
                ),
            ),
            # 2. Model attempts to mark KnowledgeState as STABLE right after an initial attempt
            AgentDecisionProposal(
                reasoning="Prematurely mark learner as stable without transfer check.",
                uncertainty_level=UncertaintyLevel.LOW,
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.UPDATE_KNOWLEDGE_STATE.value,
                    arguments={
                        "target_status": KnowledgeMasteryStatus.STABLE.value,
                        "reason": "Initial question was answered.",
                    },
                ),
            ),
        ]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=test_settings
        )

        topic = repo.get_topic_by_slug("py-conditional-branching")
        assert topic is not None
        learning_session = repo.create_session(
            topic_id=topic.id,
            current_question_id="q_py_cond_initial_01",
        )
        att_1 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_cond_initial_01",
            submitted_answer="C",
        )

        with pytest.raises(IllegalAgentToolCallError, match="Unauthorized Agent tool"):
            engine.run_diagnostic_step(
                session_id=learning_session.id,
                attempt_id=att_1.id,
            )

        with pytest.raises(UnverifiedMasteryError, match="transfer_check"):
            engine.run_diagnostic_step(
                session_id=learning_session.id,
                attempt_id=att_1.id,
            )

        blocked_events = list(
            session.scalars(
                select(DecisionEvent).where(
                    DecisionEvent.session_id == learning_session.id,
                    DecisionEvent.event_type == "illegal_agent_action_blocked",
                )
            ).all()
        )
        assert len(blocked_events) == 2


def test_model_invalid_json_and_timeout_fallback_to_retry_waiting(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify transient timeout retries succeed, while invalid JSON or persistent timeout falls back to RETRY_WAITING."""
    valid_proposal = AgentDecisionProposal(
        reasoning="Retry succeeded and selected explanation.",
        uncertainty_level=UncertaintyLevel.MEDIUM,
        selected_tool=AgentToolCallProposal(
            tool_name=AgentToolName.PROVIDE_TARGETED_EXPLANATION.value,
            arguments={
                "target_error_codes": ["list_one_based_indexing"],
                "explanation_text": "Python 列表索引从 0 开始，scores[0] 才是第一个元素。",
                "schedule_review": True,
            },
        ),
    )

    fake_provider = FakeModelProvider(
        scripted_steps=[
            # Scenario A: 1st call returns broken JSON -> non-retryable fallback to RETRY_WAITING
            "{broken_json_from_llm: true",
            # Scenario B: 1st attempt times out, 2nd attempt succeeds on retry!
            ModelTimeoutError("Simulated upstream timeout on attempt 1"),
            valid_proposal,
        ],
        max_retries=2,
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=test_settings
        )

        topic = repo.get_topic_by_slug("py-list-indexing")
        assert topic is not None
        learning_session = repo.create_session(
            topic_id=topic.id,
            current_question_id="q_py_list_initial_01",
        )
        att_1 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_list_initial_01",
            submitted_answer="70 100",
        )

        # Scenario A: Invalid JSON triggers safe fallback to RETRY_WAITING while keeping Attempt & Rule evidence
        fallback_res = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_1.id,
        )
        assert fallback_res.case_status == DiagnosticCaseStatus.RETRY_WAITING
        assert fallback_res.degraded_mode is True
        assert len(fallback_res.hypotheses_snapshot) >= 1

        # Scenario B: Re-running from RETRY_WAITING hits 1 timeout, retries automatically, and succeeds!
        recovered_res = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_1.id,
            diagnostic_case_id=fallback_res.diagnostic_case_id,
        )
        assert recovered_res.case_status == DiagnosticCaseStatus.INTERVENTION_SELECTED
        assert (
            recovered_res.executed_tool
            == AgentToolName.PROVIDE_TARGETED_EXPLANATION.value
        )
        assert recovered_res.degraded_mode is False
        assert "从 0 开始" in (recovered_res.explanation_text or "")


def test_diagnostic_step_idempotency_key_prevents_duplicate_execution(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify repeating `run_diagnostic_step` with the same `idempotency_key` does not re-call the model."""
    fake_provider = FakeModelProvider(
        scripted_steps=[
            AgentDecisionProposal(
                reasoning="Single execution.",
                uncertainty_level=UncertaintyLevel.MEDIUM,
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
                    arguments={"discriminating_reason": "Check variable trace."},
                ),
            )
        ]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=test_settings
        )

        topic = repo.get_topic_by_slug("py-variable-assignment")
        assert topic is not None
        learning_session = repo.create_session(
            topic_id=topic.id,
            current_question_id="q_py_var_initial_01",
        )
        att = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_var_initial_01",
            submitted_answer="20 25",
        )

        first = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att.id,
            idempotency_key="idem_diag_step_001",
        )
        second = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att.id,
            diagnostic_case_id=first.diagnostic_case_id,
            idempotency_key="idem_diag_step_001",
        )

        assert first.decision_event_id == second.decision_event_id
        assert first.selected_question_id == second.selected_question_id
        assert len(fake_provider.recorded_requests) == 1


def test_deepseek_and_openai_compatible_provider_contract_and_secret_redaction() -> None:
    """Verify DeepSeekProvider opt-in gate, retry on HTTP 429, fence parsing, and secret redaction."""
    req = ModelRequest(
        system_prompt="System",
        user_prompt="User",
        max_tokens=256,
    )

    # 1. Default opt-out gate blocks remote calls when allow_remote_calls=False
    disabled_provider = DeepSeekProvider(
        api_key="sk-secret-key-123456789",
        allow_remote_calls=False,
    )
    assert disabled_provider.is_configured() is False
    with pytest.raises(RemoteModelCallsDisabledError):
        disabled_provider.generate_structured(req, AgentDecisionProposal)

    # 2. Mock HTTP transport testing retry on 429 then success with markdown JSON fence
    call_counter = {"count": 0}

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return httpx.Response(429, json={"error": "rate limit"})
        proposal_json = AgentDecisionProposal(
            reasoning="Parsed from fenced JSON after 429 retry.",
            uncertainty_level=UncertaintyLevel.LOW,
            selected_tool=AgentToolCallProposal(
                tool_name=AgentToolName.PROVIDE_TARGETED_EXPLANATION.value,
                arguments={"explanation_text": "Concept explanation."},
            ),
        ).model_dump_json()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": f"```json\n{proposal_json}\n```"}}
                ],
                "usage": {
                    "prompt_tokens": 110,
                    "completion_tokens": 90,
                    "total_tokens": 200,
                },
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(_mock_handler))
    enabled_provider = DeepSeekProvider(
        api_key="sk-test-super-secret-token-9999",
        allow_remote_calls=True,
        max_retries=2,
        http_client=mock_client,
    )
    resp = enabled_provider.generate_structured(req, AgentDecisionProposal)
    assert resp.attempt_count == 2
    assert resp.usage.total_tokens == 200
    assert resp.parsed_output.selected_tool.tool_name == (
        AgentToolName.PROVIDE_TARGETED_EXPLANATION.value
    )

    # 3. Verify secret redaction strips sk-... and Bearer tokens
    leaked = "Error with header Authorization: Bearer sk-test-super-secret-token-9999 and api_key='my_secret_1234'"
    redacted = redact_sensitive_text(leaked)
    assert "sk-test-super-secret-token-9999" not in redacted
    assert "my_secret_1234" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_agent_chooses_different_interventions_based_on_followup_evidence(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify the Agent branches to different interventions depending on follow-up evidence."""
    initial_followup_step = AgentDecisionProposal(
        reasoning="Initial answer 'B' on score=85 could be careless reading or elif misconception; ask follow-up.",
        uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
        hypothesis_updates=[
            HypothesisUpdateProposal(
                error_code="cond_elif_treated_as_independent_if",
                heuristic_confidence=0.55,
                status=HypothesisStatus.CANDIDATE,
            )
        ],
        selected_tool=AgentToolCallProposal(
            tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
            arguments={"discriminating_reason": "Compare elif vs independent if."},
        ),
    )

    branch_a_explanation = AgentDecisionProposal(
        reasoning="Follow-up answer 'res1 也是 CB' confirms learner treats elif as independent if; provide explanation.",
        uncertainty_level=UncertaintyLevel.LOW,
        hypothesis_updates=[
            HypothesisUpdateProposal(
                error_code="cond_elif_treated_as_independent_if",
                heuristic_confidence=0.90,
                status=HypothesisStatus.CONFIRMED,
                evidence_items=[
                    HypothesisEvidenceProposal(
                        relation=EvidenceRelation.SUPPORTS,
                        summary="追问中认为 elif 分支在 if 命中后仍会执行。",
                    )
                ],
            )
        ],
        selected_tool=AgentToolCallProposal(
            tool_name=AgentToolName.PROVIDE_TARGETED_EXPLANATION.value,
            arguments={
                "target_error_codes": ["cond_elif_treated_as_independent_if"],
                "explanation_text": "在 if-elif 链条中，一旦首个 if 为 True，后续 elif 会直接跳过。",
                "schedule_review": True,
            },
        ),
    )

    branch_b_transfer = AgentDecisionProposal(
        reasoning="Follow-up answer '不一样，res1 是 C，res2 是 CB' rules out elif misconception; proceed to transfer check.",
        uncertainty_level=UncertaintyLevel.LOW,
        hypothesis_updates=[
            HypothesisUpdateProposal(
                error_code="cond_elif_treated_as_independent_if",
                heuristic_confidence=0.08,
                status=HypothesisStatus.RULED_OUT,
                evidence_items=[
                    HypothesisEvidenceProposal(
                        relation=EvidenceRelation.CONTRADICTS,
                        summary="追问中准确区分了 elif 短路（C）与独立 if（CB）。",
                    )
                ],
            )
        ],
        selected_tool=AgentToolCallProposal(
            tool_name=AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value,
            arguments={
                "transfer_question_id": "q_py_cond_transfer_01",
                "transfer_reason": "已排除 elif 概念误解，直接通过迁移验证题确认掌握。",
            },
        ),
    )

    fake_provider = FakeModelProvider(
        scripted_steps=[
            initial_followup_step,
            branch_a_explanation,
            initial_followup_step,
            branch_b_transfer,
        ]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=test_settings
        )
        topic = repo.get_topic_by_slug("py-conditional-branching")
        assert topic is not None

        # Branch A: Follow-up confirms misconception -> provide_targeted_explanation
        sess_a = repo.create_session(
            topic_id=topic.id,
            learner_id="learner_a",
            current_question_id="q_py_cond_initial_01",
        )
        att_a1 = repo.record_attempt(
            session_id=sess_a.id,
            question_id="q_py_cond_initial_01",
            submitted_answer="B",
        )
        step_a1 = engine.run_diagnostic_step(
            session_id=sess_a.id, attempt_id=att_a1.id
        )
        att_a2 = repo.record_attempt(
            session_id=sess_a.id,
            question_id=step_a1.selected_question_id or "q_py_cond_followup_01",
            submitted_answer="res1 也是 CB",
        )
        step_a2 = engine.run_diagnostic_step(
            session_id=sess_a.id,
            attempt_id=att_a2.id,
            diagnostic_case_id=step_a1.diagnostic_case_id,
        )
        assert (
            step_a2.executed_tool
            == AgentToolName.PROVIDE_TARGETED_EXPLANATION.value
        )
        assert step_a2.selected_intervention == InterventionAction.EXPLAIN_CONCEPT.value

        # Branch B: Follow-up contradicts misconception -> assign_transfer_verification
        sess_b = repo.create_session(
            topic_id=topic.id,
            learner_id="learner_b",
            current_question_id="q_py_cond_initial_01",
        )
        att_b1 = repo.record_attempt(
            session_id=sess_b.id,
            question_id="q_py_cond_initial_01",
            submitted_answer="B",
        )
        step_b1 = engine.run_diagnostic_step(
            session_id=sess_b.id, attempt_id=att_b1.id
        )
        att_b2 = repo.record_attempt(
            session_id=sess_b.id,
            question_id=step_b1.selected_question_id or "q_py_cond_followup_01",
            submitted_answer="不一样，res1 是 C，res2 是 CB",
        )
        step_b2 = engine.run_diagnostic_step(
            session_id=sess_b.id,
            attempt_id=att_b2.id,
            diagnostic_case_id=step_b1.diagnostic_case_id,
        )
        assert (
            step_b2.executed_tool
            == AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value
        )
        assert step_b2.selected_intervention == InterventionAction.TRANSFER_CHECK.value
        assert step_b2.selected_question_id == "q_py_cond_transfer_01"


def test_same_transfer_question_retry_cannot_promote_to_stable(
    session_factory: sessionmaker[Session],
) -> None:
    """Core Principle Test: A failed transfer question retried and answered correctly CANNOT promote to STABLE."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        topic = repo.get_topic_by_slug("py-for-loop")
        assert topic is not None

        learning_session = repo.create_session(
            topic_id=topic.id,
            learner_id="learner_retry_test",
            current_question_id="q_py_loop_transfer_01",
        )

        # First attempt on q_py_loop_transfer_01 fails
        fail_attempt = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_loop_transfer_01",
            submitted_answer="3 15",
            is_correct=False,
            evaluation_status="evaluated",
        )
        # Update knowledge state to needs_practice
        repo.update_knowledge_state(
            session_id=learning_session.id,
            topic_id=topic.id,
            target_status=KnowledgeMasteryStatus.NEEDS_PRACTICE,
            reason="Transfer question failed.",
            learner_id="learner_retry_test",
            transfer_attempt_id=fail_attempt.id,
        )

        # Learner retries the EXACT SAME transfer question and gets it right
        retry_correct_attempt = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_loop_transfer_01",
            submitted_answer="3 17",
            is_correct=True,
            evaluation_status="evaluated",
        )

        # Domain rule MUST block this from being recognized as STABLE!
        with pytest.raises(UnverifiedMasteryError, match="using a retried transfer question"):
            repo.update_knowledge_state(
                session_id=learning_session.id,
                topic_id=topic.id,
                target_status=KnowledgeMasteryStatus.STABLE,
                reason="Learner got the same transfer question right on second try.",
                learner_id="learner_retry_test",
                transfer_attempt_id=retry_correct_attempt.id,
            )


def test_exhausted_transfer_questions_safely_degrades_without_false_mastery(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify when all transfer questions are exhausted, Agent tool degrades safely rather than recycling."""
    fake_provider = FakeModelProvider(
        scripted_steps=[
            AgentDecisionProposal(
                reasoning="Request another transfer check.",
                uncertainty_level=UncertaintyLevel.MEDIUM,
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value,
                    arguments={"transfer_reason": "Verify transfer."},
                ),
            )
        ]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=test_settings
        )
        topic = repo.get_topic_by_slug("py-variable-assignment")
        assert topic is not None

        learning_session = repo.create_session(
            topic_id=topic.id,
            learner_id="learner_exhaust_test",
            current_question_id="q_py_var_transfer_01",
        )

        # Pre-attempt the only transfer question for py-variable-assignment
        prior_transfer = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_var_transfer_01",
            submitted_answer="100 70",
            is_correct=False,
            evaluation_status="evaluated",
        )

        # Agent runs diagnostic step and requests assign_transfer_verification
        result = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=prior_transfer.id,
        )

        # Must degrade cleanly because no unattempted transfer questions remain!
        assert result.executed_tool == "exhausted_transfer_questions_degrade"
        assert result.case_status == DiagnosticCaseStatus.INSUFFICIENT_EVIDENCE
        assert result.selected_intervention == InterventionAction.SCHEDULE_REVIEW.value
        assert result.degraded_mode is True
        assert "暂无未作答过的独立新情境迁移验证题" in (result.degradation_reason or "")


def test_token_budget_pre_call_reservation_guard(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Verify pre-call reservation guard intercepts when remaining budget is below 256 tokens."""
    budget_settings = test_settings.model_copy(
        update={"diagnostic_session_token_budget": 500}
    )
    fake_provider = FakeModelProvider(
        scripted_steps=[
            (
                AgentDecisionProposal(
                    reasoning="Initial follow-up.",
                    uncertainty_level=UncertaintyLevel.MEDIUM,
                    selected_tool=AgentToolCallProposal(
                        tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
                        arguments={"discriminating_reason": "Followup."},
                    ),
                ),
                TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300),
            )
        ]
    )

    with transactional_session(session_factory) as session:
        import_content_pack(session)
        repo = LearningRepository(session)
        engine = DiagnosticAgentEngine(
            session, fake_provider, settings=budget_settings
        )
        topic = repo.get_topic_by_slug("py-range-function")
        assert topic is not None
        learning_session = repo.create_session(
            topic_id=topic.id,
            current_question_id="q_py_range_initial_01",
        )

        # Call 1: Consumes 300 tokens out of 500. Remaining budget = 200 tokens (< MIN_RESERVED 256).
        att_1 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_range_initial_01",
            submitted_answer="[1, 2, 3, 4, 5]",
        )
        res_1 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_1.id,
        )
        assert res_1.tokens_used_in_case == 300
        assert res_1.degraded_mode is False

        # Call 2: Pre-call guard MUST intercept before calling the model!
        att_2 = repo.record_attempt(
            session_id=learning_session.id,
            question_id="q_py_range_followup_01",
            submitted_answer="[1, 2, 3]",
        )
        res_2 = engine.run_diagnostic_step(
            session_id=learning_session.id,
            attempt_id=att_2.id,
            diagnostic_case_id=res_1.diagnostic_case_id,
        )
        assert res_2.degraded_mode is True
        assert res_2.executed_tool == "budget_limit_degrade"
        assert "低于单次调用最小预留安全阈值" in (res_2.degradation_reason or "")
        assert len(fake_provider.recorded_requests) == 1  # Model was not called for turn 2!


def test_migration_0001_to_0002_upgrade_data_integrity(
    test_settings: Settings,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Verify incremental Alembic migration from 0001 to 0002 preserves existing Stage 2 records."""
    from pathlib import Path
    from app.persistence.database import create_db_engine, create_session_factory
    from app.persistence.migrations_runner import upgrade_database

    migration_db_path = Path(str(tmp_path)) / "migration_integrity.db"
    migration_url = f"sqlite:///{migration_db_path.as_posix()}"
    engine = create_db_engine(database_url=migration_url)

    try:
        # Step 1: Upgrade only to Stage 2 schema (revision 0001)
        upgrade_database(
            database_url=migration_url,
            engine=engine,
            revision="0001_initial_stage2_schema",
        )
        factory = create_session_factory(engine)

        from tests.conftest import seed_historical_question
        seed_historical_question(engine, "topic_py_var_assign", "py-var-assign", "q_py_var_initial_01")
        # Historical ORM mappings include columns that did not exist at revision 0001.
        # Insert through the actual 0001 schema to keep this migration test meaningful.
        from sqlalchemy import text
        saved_sess_id = "migration_0001_session"
        saved_att_id = "migration_0001_attempt"
        saved_evt_id = "migration_0001_event"
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO learning_sessions (id, learner_id, topic_id, current_question_id, status, started_at, updated_at) VALUES (:id, :learner, :topic, :question, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"id": saved_sess_id, "learner": "local_default_learner", "topic": "topic_py_var_assign", "question": "q_py_var_initial_01"})
            connection.execute(text("INSERT INTO attempts (id, session_id, question_id, question_version, question_snapshot_json, attempt_role, submitted_answer, is_correct, evaluation_status, submitted_at) VALUES (:id, :session, :question, 1, '{}', 'initial', '20 15', 1, 'evaluated', CURRENT_TIMESTAMP)"), {"id": saved_att_id, "session": saved_sess_id, "question": "q_py_var_initial_01"})
            connection.execute(text("INSERT INTO decision_events (id, session_id, event_type, to_state, action, reason, uncertainty_level, payload_json, created_at) VALUES (:id, :session, 'stage2_baseline_event', 'active', 'test_seed', 'Pre-migration event.', 'low', '{}', CURRENT_TIMESTAMP)"), {"id": saved_evt_id, "session": saved_sess_id})

        # Step 2: Incrementally upgrade to Stage 3 schema (revision 0002_stage3_model_calls)
        upgrade_database(
            database_url=migration_url,
            engine=engine,
            revision="0002_stage3_model_calls",
        )

        # At this historical revision the current ORM includes columns added by
        # later migrations. Verify the 0001→0002 data with SQL, then advance the
        # isolated fixture to head before loading current ORM models.
        with engine.connect() as connection:
            assert connection.execute(text("SELECT id FROM learning_sessions WHERE id=:id"), {"id": saved_sess_id}).scalar_one() == saved_sess_id
            assert connection.execute(text("SELECT submitted_answer FROM attempts WHERE id=:id"), {"id": saved_att_id}).scalar_one() == "20 15"
            assert connection.execute(text("SELECT action FROM decision_events WHERE id=:id"), {"id": saved_evt_id}).scalar_one() == "test_seed"
        upgrade_database(database_url=migration_url, engine=engine)

        with transactional_session(factory) as session:
            # Verify existing Stage 2 records remain completely intact
            retrieved_sess = session.get(LearningSession, saved_sess_id)
            retrieved_att = session.get(Attempt, saved_att_id)
            retrieved_evt = session.get(DecisionEvent, saved_evt_id)
            assert retrieved_sess is not None
            assert retrieved_att is not None and retrieved_att.submitted_answer == "20 15"
            assert retrieved_evt is not None and retrieved_evt.action == "test_seed"

            # Verify new model_calls table is operational with foreign key constraints
            repo = LearningRepository(session)
            mcall = repo.record_model_call(
                provider_name="deepseek",
                model_name="deepseek-chat",
                prompt_version="v1",
                status=ModelCallStatus.SUCCEEDED,
                redacted_summary="Post-migration audit call.",
                session_id=saved_sess_id,
                decision_event_id=saved_evt_id,
            )
            assert mcall.id.startswith("mcall_")
            assert mcall.session_id == saved_sess_id
    finally:
        engine.dispose()

