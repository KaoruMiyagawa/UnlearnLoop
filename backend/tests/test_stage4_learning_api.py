"""Stage 4 HTTP integration and REST API contract tests for UnlearnLoop.

All tests execute 100% offline using isolated temporary SQLite databases
and FastAPI TestClient. Covers the complete learning loop:
Catalog -> Session -> Attempt -> Diagnosis -> Discrimination -> Practice -> Transfer -> Mastery.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.dependencies import get_model_provider, get_session_factory
from app.config import Settings, get_settings
from app.decision import (
    AgentDecisionProposal,
    AgentToolCallProposal,
    HypothesisEvidenceProposal,
    HypothesisUpdateProposal,
)
from app.domain.enums import (
    AgentToolName,
    EvidenceRelation,
    HypothesisStatus,
    KnowledgeMasteryStatus,
    SessionStatus,
    UncertaintyLevel,
)
from app.main import create_app
from app.model_provider import (
    FakeModelProvider,
    ModelTimeoutError,
    TokenUsage,
)
from app.persistence.database import transactional_session
from app.persistence.seed import import_content_pack


@pytest.fixture
def seeded_client(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> Iterator[TestClient]:
    """TestClient bound to a temporary SQLite database pre-seeded with the python basics content pack."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)

    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    yield TestClient(app)


# ---------------------------------------------------------------------------
# Test 1 & 17: Content Discovery & Sanitization Security Contract
# ---------------------------------------------------------------------------


def test_topics_catalog_and_sanitized_question_security_contract(
    seeded_client: TestClient,
) -> None:
    """1 & 17. Verify topic list and ensure playable questions never leak standard answers or rubrics."""
    resp = seeded_client.get("/api/v1/topics")
    assert resp.status_code == 200
    topics = resp.json()
    assert len(topics) == 5
    topic_slugs = {t["slug"] for t in topics}
    assert "py-for-loop" in topic_slugs
    assert "py-variable-assignment" in topic_slugs

    # Fetch detail of py-for-loop
    detail_resp = seeded_client.get("/api/v1/topics/py-for-loop")
    assert detail_resp.status_code == 200
    topic_data = detail_resp.json()
    assert topic_data["slug"] == "py-for-loop"
    assert len(topic_data["prerequisites"]) == 2
    assert len(topic_data["materials"]) == 1
    assert topic_data["questions_count"] >= 4

    # Fetch questions directly and verify security contract
    q_resp = seeded_client.get("/api/v1/questions/q_py_loop_initial_01")
    assert q_resp.status_code == 200
    q_data = q_resp.json()

    # Public question fields present
    assert q_data["id"] == "q_py_loop_initial_01"
    assert "for" in q_data["context_snippet"]
    assert q_data["question_role"] == "initial"

    # CRITICAL SECURITY CONTRACT: Sensitive evaluation internals MUST NOT be present
    assert "standard_answer" not in q_data
    assert "answer_explanation" not in q_data
    assert "evaluation_rubric" not in q_data
    assert "target_error_codes" not in q_data


# ---------------------------------------------------------------------------
# Test 2 & 3 & 13: Learning Session Creation, Attempts & Idempotency
# ---------------------------------------------------------------------------


def test_session_creation_attempt_recording_and_idempotency(
    seeded_client: TestClient,
) -> None:
    """2, 3, 13. Verify session lifecycle, immutable attempt creation, and idempotency protection."""
    # Step 1: Create session
    create_resp = seeded_client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop", "learner_id": "learner_alice"},
    )
    assert create_resp.status_code == 201
    session_data = create_resp.json()
    sess_id = session_data["id"]
    assert session_data["status"] == "active"
    assert session_data["current_question_id"] == "q_py_loop_initial_01"
    assert session_data["current_question"]["id"] == "q_py_loop_initial_01"

    # Step 2: Submit an attempt with an idempotency key
    attempt_payload = {
        "question_id": "q_py_loop_initial_01",
        "submitted_answer": "4",
        "idempotency_key": "idem_sub_001",
    }
    att_resp_1 = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json=attempt_payload,
    )
    assert att_resp_1.status_code == 201
    att_data_1 = att_resp_1.json()
    assert att_data_1["is_correct"] is False
    assert att_data_1["next_action"] == "diagnose"
    att_id_1 = att_data_1["attempt_id"]

    # Step 3: Duplicate submission with same idempotency key returns identical attempt without re-executing
    att_resp_duplicate = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json=attempt_payload,
    )
    assert att_resp_duplicate.status_code == 201
    att_data_dup = att_resp_duplicate.json()
    assert att_data_dup["attempt_id"] == att_id_1

    # Verify session attempts list has exactly 1 attempt
    history_resp = seeded_client.get(f"/api/v1/sessions/{sess_id}/attempts")
    assert history_resp.status_code == 200
    assert len(history_resp.json()) == 1

    # Inspect immutable attempt detail
    detail_att_resp = seeded_client.get(f"/api/v1/attempts/{att_id_1}")
    assert detail_att_resp.status_code == 200
    att_detail = detail_att_resp.json()
    assert att_detail["submitted_answer"] == "4"
    assert att_detail["idempotency_key"] == "idem_sub_001"


# ---------------------------------------------------------------------------
# Test 4 & 5 & 6 & 7: Wrong Answer, Diagnostic Case, Hypotheses & Evidence
# ---------------------------------------------------------------------------


def test_wrong_answer_triggers_diagnosis_hypotheses_and_followup(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """4, 5, 6, 7. Verify diagnostic case creation, candidate hypotheses, Agent followup selection, and evidence updates."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)

    # Fake model will return SELECT_DIAGNOSTIC_FOLLOWUP on first step
    fake_provider = FakeModelProvider(
        scripted_steps=[
            AgentDecisionProposal(
                reasoning="Learner wrote output 4 without trace; check range starting index.",
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                uncertainty_note="Needs per-iteration trace output.",
                hypothesis_updates=[
                    HypothesisUpdateProposal(
                        error_code="range_stop_inclusive",
                        heuristic_confidence=0.65,
                        status=HypothesisStatus.CANDIDATE,
                        evidence_items=[
                            HypothesisEvidenceProposal(
                                relation=EvidenceRelation.SUPPORTS,
                                summary="Answer 4 indicates inclusive range stop.",
                            )
                        ],
                    )
                ],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
                    arguments={
                        "followup_question_id": "q_py_loop_followup_01",
                        "target_error_codes": ["range_stop_inclusive"],
                        "discriminating_reason": "Ask per-iteration trace print.",
                    },
                ),
            )
        ]
    )

    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_model_provider] = lambda: fake_provider
    client = TestClient(app)

    # 1. Start session
    sess_res = client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop", "learner_id": "learner_diag_test"},
    ).json()
    sess_id = sess_res["id"]

    # 2. Submit wrong answer '4'
    att_res = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "4"},
    ).json()
    assert att_res["is_correct"] is False
    assert att_res["next_action"] == "diagnose"
    diag_case_id = att_res["diagnostic_case_id"]
    assert diag_case_id is not None

    # 3. Query diagnostic case detail & hypotheses
    case_resp = client.get(f"/api/v1/diagnoses/{diag_case_id}")
    assert case_resp.status_code == 200
    case_data = case_resp.json()
    assert case_data["id"] == diag_case_id
    assert case_data["session_id"] == sess_id

    # 4. Trigger Agent diagnostic step
    step_resp = client.post(f"/api/v1/diagnoses/{diag_case_id}/step")
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["executed_tool"] == "select_diagnostic_followup"
    assert step_data["selected_question_id"] == "q_py_loop_followup_01"
    assert step_data["next_question"]["id"] == "q_py_loop_followup_01"
    # Ensure next question is sanitized
    assert "standard_answer" not in step_data["next_question"]

    # 5. Check hypotheses and evidence links endpoints
    hyps_resp = client.get(f"/api/v1/diagnoses/{diag_case_id}/hypotheses")
    assert hyps_resp.status_code == 200
    assert len(hyps_resp.json()) >= 1

    ev_resp = client.get(f"/api/v1/diagnoses/{diag_case_id}/evidence")
    assert ev_resp.status_code == 200
    assert len(ev_resp.json()) >= 1

    # 6. Submit follow-up response
    followup_att_resp = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={
            "question_id": "q_py_loop_followup_01",
            "submitted_answer": "依次打印 1、3",
        },
    )
    assert followup_att_resp.status_code == 201
    followup_data = followup_att_resp.json()
    assert followup_data["next_action"] == "diagnose_step"


# ---------------------------------------------------------------------------
# Test 8 & 9 & 10 & 11: Complete End-to-End Learning Loop & Transfer Check
# ---------------------------------------------------------------------------


def test_full_end_to_end_learning_loop_with_transfer_check_and_mastery(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Complete End-to-End HTTP test from session start to verified transfer check:
    1. Start session on py-for-loop.
    2. Submit bare '3' -> enters diagnosis.
    3. Agent asks follow-up -> learner answers '依次打印 1、3' -> confirms range_start_at_one.
    4. Agent assigns targeted practice -> learner answers practice '6' correctly.
    5. Agent assigns transfer check 1 (`q_py_loop_transfer_01`).
    6. Transfer check 1 fails ('3 15') -> retains needs_practice, review scheduled.
    7. Retrying the SAME transfer check 1 with correct answer '3 17' MUST NOT grant stable!
    8. Dispatch independent fresh transfer check 2 (`q_py_loop_transfer_02`).
    9. Answer transfer check 2 correctly ('3 60') -> legally updates KnowledgeState to STABLE!
    10. Complete session and verify profile and reviews.
    """
    with transactional_session(session_factory) as session:
        import_content_pack(session)

    fake_provider = FakeModelProvider(
        scripted_steps=[
            # Step 1: After initial '3', ask follow-up
            AgentDecisionProposal(
                reasoning="Initial answer 3 lacks iteration trace; prompt with follow-up.",
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                hypothesis_updates=[
                    HypothesisUpdateProposal(
                        error_code="range_start_at_one",
                        heuristic_confidence=0.45,
                        status=HypothesisStatus.CANDIDATE,
                    )
                ],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
                    arguments={
                        "followup_question_id": "q_py_loop_followup_01",
                        "target_error_codes": ["range_start_at_one"],
                        "discriminating_reason": "Differentiate range(3) starting at 0 vs 1.",
                    },
                ),
            ),
            # Step 2: After follow-up '依次打印 1、3', assign targeted practice
            AgentDecisionProposal(
                reasoning="Follow-up confirmed range_start_at_one; assign targeted practice.",
                uncertainty_level=UncertaintyLevel.LOW,
                hypothesis_updates=[
                    HypothesisUpdateProposal(
                        error_code="range_start_at_one",
                        heuristic_confidence=0.88,
                        status=HypothesisStatus.CONFIRMED,
                    )
                ],
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.ASSIGN_TARGETED_PRACTICE.value,
                    arguments={
                        "practice_question_id": "q_py_loop_practice_01",
                        "target_error_codes": ["range_start_at_one"],
                        "practice_reason": "Practice loop indexing with range(1, 4).",
                    },
                ),
            ),
            # Step 3: After practice '6', assign transfer check
            AgentDecisionProposal(
                reasoning="Practice passed; assign transfer check 1.",
                uncertainty_level=UncertaintyLevel.LOW,
                selected_tool=AgentToolCallProposal(
                    tool_name=AgentToolName.ASSIGN_TRANSFER_VERIFICATION.value,
                    arguments={
                        "transfer_question_id": "q_py_loop_transfer_01",
                        "transfer_reason": "Verify knowledge transfer in inventory context.",
                    },
                ),
            ),
        ]
    )

    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_model_provider] = lambda: fake_provider
    client = TestClient(app)

    learner_id = "learner_e2e_full"

    # Step 1: Create session
    s_resp = client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop", "learner_id": learner_id},
    )
    assert s_resp.status_code == 201
    sess_id = s_resp.json()["id"]

    # Step 2: Submit bare '3' on initial question
    att_1 = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "3"},
    ).json()
    assert att_1["next_action"] == "diagnose"
    diag_case_id = att_1["diagnostic_case_id"]

    # Step 3: Run Agent step 1 -> selects followup
    step_1 = client.post(f"/api/v1/diagnoses/{diag_case_id}/step").json()
    assert step_1["executed_tool"] == "select_diagnostic_followup"
    assert step_1["selected_question_id"] == "q_py_loop_followup_01"

    # Step 4: Submit follow-up response
    att_2 = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={
            "question_id": "q_py_loop_followup_01",
            "submitted_answer": "依次打印 1、3",
        },
    ).json()
    assert att_2["next_action"] == "diagnose_step"

    # Step 5: Run Agent step 2 -> assigns targeted practice
    step_2 = client.post(f"/api/v1/diagnoses/{diag_case_id}/step").json()
    assert step_2["executed_tool"] == "assign_targeted_practice"
    assert step_2["selected_question_id"] == "q_py_loop_practice_01"

    # Step 6: Submit targeted practice answer '6' (correct)
    att_3 = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_practice_01", "submitted_answer": "6"},
    ).json()
    assert att_3["is_correct"] is True
    assert att_3["next_action"] == "transfer_check"

    # Step 7: Run Agent step 3 -> assigns transfer verification 1
    step_3 = client.post(f"/api/v1/diagnoses/{diag_case_id}/step").json()
    assert step_3["executed_tool"] == "assign_transfer_verification"
    assert step_3["selected_question_id"] == "q_py_loop_transfer_01"

    # Step 8: Submit WRONG answer '3 15' on transfer check 1
    att_4 = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_transfer_01", "submitted_answer": "3 15"},
    ).json()
    assert att_4["is_correct"] is False
    assert att_4["next_action"] == "transfer_failed_needs_practice"
    assert att_4["knowledge_state_status"] == KnowledgeMasteryStatus.NEEDS_PRACTICE.value

    # Step 9: Retrying the SAME transfer check 1 with correct answer '3 17' CANNOT grant stable!
    att_retry_same = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_transfer_01", "submitted_answer": "3 17"},
    ).json()
    assert att_retry_same["is_correct"] is True
    assert att_retry_same["next_action"] == "transfer_retry_blocked"
    assert att_retry_same["knowledge_state_status"] == KnowledgeMasteryStatus.NEEDS_PRACTICE.value

    # Verify review item was scheduled
    rev_resp = client.get(f"/api/v1/reviews?learner_id={learner_id}")
    assert rev_resp.status_code == 200
    reviews = rev_resp.json()
    assert len(reviews) >= 1
    review_id = reviews[0]["id"]

    # Step 10: Dispatch independent fresh transfer question 2
    dispatch_resp = client.post(f"/api/v1/sessions/{sess_id}/transfer-check")
    assert dispatch_resp.status_code == 200
    dispatch_data = dispatch_resp.json()
    assert dispatch_data["degraded"] is False
    q_transfer_2 = dispatch_data["question"]
    assert q_transfer_2["id"] == "q_py_loop_transfer_02"

    # Step 11: Submit correct answer '3 60' for fresh transfer question 2
    att_fresh_transfer = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_transfer_02", "submitted_answer": "3 60"},
    ).json()
    assert att_fresh_transfer["is_correct"] is True
    assert att_fresh_transfer["next_action"] == "mastery_achieved"
    assert att_fresh_transfer["knowledge_state_status"] == KnowledgeMasteryStatus.STABLE.value

    # Step 12: Complete session legally
    complete_resp = client.post(f"/api/v1/sessions/{sess_id}/complete")
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"

    # Step 13: Complete scheduled review task
    comp_rev_resp = client.post(
        f"/api/v1/reviews/{review_id}/complete",
        json={"review_notes": "Reviewed loop range indexing logic."},
    )
    assert comp_rev_resp.status_code == 200
    assert comp_rev_resp.json()["status"] == "completed"

    # Step 14: Check learner dashboard and profile
    profile_resp = client.get(f"/api/v1/profile/knowledge-states?learner_id={learner_id}")
    assert profile_resp.status_code == 200
    states = profile_resp.json()
    assert len(states) >= 1
    loop_state = next(s for s in states if s["topic_slug"] == "py-for-loop")
    assert loop_state["status"] == "stable"
    assert loop_state["confidence_is_heuristic"] is True

    summary_resp = client.get(f"/api/v1/profile/summary?learner_id={learner_id}")
    assert summary_resp.status_code == 200
    sum_data = summary_resp.json()
    assert sum_data["total_sessions"] >= 1
    assert sum_data["completed_sessions"] >= 1
    assert sum_data["mastered_topics_count"] >= 1


# ---------------------------------------------------------------------------
# Test 12: Review Management & Profile Dashboard Endpoints
# ---------------------------------------------------------------------------


def test_reviews_and_profile_dashboard_endpoints(seeded_client: TestClient) -> None:
    """12. Verify listing and completing reviews, and profile dashboard summary aggregation."""
    # List empty reviews
    resp = seeded_client.get("/api/v1/reviews?learner_id=new_learner")
    assert resp.status_code == 200
    assert resp.json() == []

    # Get empty profile summary
    dash_resp = seeded_client.get("/api/v1/profile/summary?learner_id=new_learner")
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert dash_data["learner_id"] == "new_learner"
    assert dash_data["total_sessions"] == 0
    assert dash_data["mastered_topics_count"] == 0


# ---------------------------------------------------------------------------
# Test 14: Illegal State Transition HTTP Error Mapping (409 / 400)
# ---------------------------------------------------------------------------


def test_illegal_session_operations_and_state_transition_errors(
    seeded_client: TestClient,
) -> None:
    """14. Verify illegal operations (e.g., resuming active session, completing active session) return clean 400/409."""
    # Create session (status: active)
    sess_res = seeded_client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop"},
    ).json()
    sess_id = sess_res["id"]

    # 1. Resuming an already active session must fail with 400
    resume_resp = seeded_client.post(f"/api/v1/sessions/{sess_id}/resume")
    assert resume_resp.status_code == 400
    assert resume_resp.json()["code"] == "INVALID_SESSION_STATE"

    # 2. Completing an active session (without transfer check) must fail with 409
    complete_resp = seeded_client.post(f"/api/v1/sessions/{sess_id}/complete")
    assert complete_resp.status_code == 409
    assert complete_resp.json()["code"] == "INVALID_STATE_TRANSITION"

    # 3. Submitting answers to a question belonging to another topic must fail with 400
    bad_q_resp = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_var_initial_01", "submitted_answer": "10"},
    )
    assert bad_q_resp.status_code == 400
    assert bad_q_resp.json()["code"] == "DOMAIN_RULE_VIOLATION"


# ---------------------------------------------------------------------------
# Test 15: Model Timeout, Retry Recovery & Budget Interception
# ---------------------------------------------------------------------------


def test_model_timeout_retry_waiting_and_recovery(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """15. Verify model timeout transitions diagnostic case to RETRY_WAITING, and retry endpoint recovers cleanly."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)

    # First call will raise ModelTimeoutError (with max_retries=0 to exhaust immediately); retry will succeed
    flaky_provider = FakeModelProvider(
        scripted_steps=[
            ModelTimeoutError("Simulated LLM Gateway timeout", latency_ms=10000),
        ],
        max_retries=0,
    )

    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_model_provider] = lambda: flaky_provider
    client = TestClient(app)

    # Create session & trigger diagnostic case with wrong answer
    sess_res = client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop"},
    ).json()
    sess_id = sess_res["id"]

    att_res = client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "wrong"},
    ).json()
    diag_case_id = att_res["diagnostic_case_id"]

    # Step 1: Model times out -> handled cleanly into retry_waiting fallback state
    step_resp = client.post(f"/api/v1/diagnoses/{diag_case_id}/step")
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["case_status"] == "retry_waiting"
    assert step_data["executed_tool"] == "enter_retry_waiting"
    assert step_data["degraded_mode"] is True

    # Verify diagnostic case entered RETRY_WAITING
    case_resp = client.get(f"/api/v1/diagnoses/{diag_case_id}")
    assert case_resp.status_code == 200
    assert case_resp.json()["status"] == "retry_waiting"

    # Step 2: Enqueue success response and call retry endpoint -> recovers and executes step
    flaky_provider.enqueue(
        AgentDecisionProposal(
            reasoning="Recovered from timeout.",
            uncertainty_level=UncertaintyLevel.LOW,
            selected_tool=AgentToolCallProposal(
                tool_name=AgentToolName.SELECT_DIAGNOSTIC_FOLLOWUP.value,
                arguments={
                    "followup_question_id": "q_py_loop_followup_01",
                    "discriminating_reason": "Follow up after timeout recovery.",
                },
            ),
        )
    )
    retry_resp = client.post(f"/api/v1/diagnoses/{diag_case_id}/retry")
    assert retry_resp.status_code == 200
    retry_data = retry_resp.json()
    assert retry_data["executed_tool"] == "select_diagnostic_followup"
    assert retry_data["case_status"] == "question_selected"


def test_token_budget_interception_via_api(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """16. Verify token budget pre-call reservation guard degrades cleanly via API when budget is exceeded."""
    budget_settings = test_settings.model_copy(
        update={"diagnostic_session_token_budget": 350}
    )
    with transactional_session(session_factory) as session:
        import_content_pack(session)

    # Turn 1 consumes 300 tokens out of 350. Turn 2 will be intercepted by pre-call reservation guard (remaining 50 < 256).
    fake_provider = FakeModelProvider(
        scripted_steps=[
            (
                AgentDecisionProposal(
                    reasoning="Initial followup.",
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

    app = create_app(budget_settings)
    app.dependency_overrides[get_settings] = lambda: budget_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_model_provider] = lambda: fake_provider
    client = TestClient(app)

    sess = client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop"},
    ).json()
    att = client.post(
        f"/api/v1/sessions/{sess['id']}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "99"},
    ).json()
    diag_id = att["diagnostic_case_id"]

    # Turn 1 succeeds
    t1_resp = client.post(f"/api/v1/diagnoses/{diag_id}/step")
    assert t1_resp.status_code == 200
    assert t1_resp.json()["degraded_mode"] is False

    # Turn 2 is intercepted by token budget guard -> safe degradation
    t2_resp = client.post(f"/api/v1/diagnoses/{diag_id}/step")
    assert t2_resp.status_code == 200
    t2_data = t2_resp.json()
    assert t2_data["degraded_mode"] is True
    assert t2_data["executed_tool"] == "budget_limit_degrade"
    assert "低于单次调用最小预留安全阈值" in t2_data["degradation_reason"]
