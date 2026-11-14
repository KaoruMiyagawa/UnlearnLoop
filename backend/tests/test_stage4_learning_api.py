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
    # CRITICAL SECURITY CONTRACT: TopicDetailResponse MUST NOT leak internal common_error_patterns
    assert "common_error_patterns" not in topic_data

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


def test_fake_provider_can_select_practice_without_hypothesis_updates(
    seeded_client: TestClient,
) -> None:
    """An intervention may follow a diagnostic question even when the Agent leaves hypotheses unchanged."""
    session_resp = seeded_client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop", "learner_id": "learner_fake_practice"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    initial = seeded_client.post(
        f"/api/v1/sessions/{session_id}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "4"},
    ).json()
    case_id = initial["diagnostic_case_id"]

    first_step = seeded_client.post(f"/api/v1/diagnoses/{case_id}/step")
    assert first_step.status_code == 200
    followup = first_step.json()["next_question"]
    assert followup["question_role"] == "diagnostic_followup"

    duplicate_step = seeded_client.post(f"/api/v1/diagnoses/{case_id}/step")
    assert duplicate_step.status_code == 400
    assert duplicate_step.json()["code"] == "INVALID_SESSION_STATE"
    still_waiting = seeded_client.get(f"/api/v1/sessions/{session_id}").json()
    assert still_waiting["current_question_id"] == followup["id"]

    followup_result = seeded_client.post(
        f"/api/v1/sessions/{session_id}/attempts",
        json={
            "question_id": followup["id"],
            "submitted_answer": "I can trace the total after each iteration.",
        },
    )
    assert followup_result.status_code == 201
    assert followup_result.json()["next_action"] == "diagnose_step"

    second_step = seeded_client.post(f"/api/v1/diagnoses/{case_id}/step")
    assert second_step.status_code == 200
    result = second_step.json()
    assert result["selected_intervention"] == "targeted_practice"
    assert result["next_question"]["question_role"] == "targeted_practice"

    current = seeded_client.get(f"/api/v1/sessions/{session_id}")
    assert current.status_code == 200
    assert current.json()["current_question_id"] == result["next_question"]["id"]


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

    # The service dispatches the transfer question with the practice result;
    # do not run another Agent step while that server question is unanswered.
    session_after_practice = client.get(f"/api/v1/sessions/{sess_id}").json()
    assert session_after_practice["current_question_id"] == "q_py_loop_transfer_01"

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
    scheduled_after_transfer = client.get(f"/api/v1/reviews?learner_id={learner_id}").json()
    assert any(item["retention_eligible"] and item["is_due"] is False for item in scheduled_after_transfer)

    # Step 12: Complete session legally
    complete_resp = client.post(f"/api/v1/sessions/{sess_id}/complete")
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"

    # Step 13: A review task cannot be completed without an assigned question and evaluated answer.
    comp_rev_resp = client.post(
        f"/api/v1/reviews/{review_id}/complete",
        json={"review_notes": "Reviewed loop range indexing logic."},
    )
    assert comp_rev_resp.status_code == 400
    assert comp_rev_resp.json()["code"] == "DOMAIN_RULE_VIOLATION"

    # Step 14: Check learner dashboard and profile
    profile_resp = client.get(f"/api/v1/profile/knowledge-states?learner_id={learner_id}")
    assert profile_resp.status_code == 200
    states = profile_resp.json()
    assert len(states) >= 1
    loop_state = next(s for s in states if s["topic_slug"] == "py-for-loop")
    assert loop_state["status"] == "stable"
    assert loop_state["confidence_is_heuristic"] is True
    assert loop_state["retention_status"] == "review_due"

    history_resp = client.get(f"/api/v1/profile/history?learner_id={learner_id}")
    assert history_resp.status_code == 200
    history = history_resp.json()
    history_kinds = {event["kind"] for event in history}
    assert {"incorrect_answer", "diagnosis", "diagnostic_question", "targeted_practice",
            "transfer_check", "review_scheduled"}.issubset(history_kinds)
    assert all("submitted_answer" not in event for event in history)
    assert all("payload_json" not in event for event in history)

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

    followup_question = t1_resp.json()["next_question"]
    followup_resp = client.post(
        f"/api/v1/sessions/{sess['id']}/attempts",
        json={
            "question_id": followup_question["id"],
            "submitted_answer": "The loop visits each value once.",
        },
    )
    assert followup_resp.status_code == 201
    assert followup_resp.json()["next_action"] == "diagnose_step"

    # After the dispatched follow-up has an answer, the token budget guard safely degrades.
    t2_resp = client.post(f"/api/v1/diagnoses/{diag_id}/step")
    assert t2_resp.status_code == 200
    t2_data = t2_resp.json()
    assert t2_data["degraded_mode"] is True
    assert t2_data["executed_tool"] == "budget_limit_degrade"
    assert "低于单次调用最小预留安全阈值" in t2_data["degradation_reason"]


# ---------------------------------------------------------------------------
# Audit Regression Tests (Stage 4 Final Source Review)
# ---------------------------------------------------------------------------


def test_real_database_dependency_path_without_overrides_and_engine_reuse(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit Item 1 & 6: Exercise real get_session_factory / get_db without dependency_overrides in development mode."""
    from pathlib import Path
    from app.api.v1.dependencies import (
        _ENGINE_CACHE,
        clear_engine_cache,
        get_session_factory as real_get_session_factory,
    )

    clear_engine_cache()
    db_file = Path(str(tmp_path)) / "dev_real_dep.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ALLOW_REMOTE_MODEL_CALLS", "false")
    get_settings.cache_clear()

    try:
        dev_settings = get_settings()
        assert dev_settings.app_env == "development"

        app = create_app(dev_settings)
        # Crucial: ZERO dependency_overrides on app! Exercises real get_settings -> get_session_factory -> get_db
        assert app.dependency_overrides == {}

        with TestClient(app) as client:
            resp1 = client.get("/api/v1/topics")
            assert resp1.status_code == 200
            topics = resp1.json()
            assert len(topics) == 13  # Adds two Matching Headings topics to the existing eleven.
            assert {"ielts-mh-academic", "ielts-mh-general-training"} <= {topic["id"] for topic in topics}

            # Verify Engine was cached once and is reused across subsequent requests
            assert len(_ENGINE_CACHE) == 1
            cached_engine_1, cached_factory_1 = next(iter(_ENGINE_CACHE.values()))

            resp2 = client.get("/api/v1/topics/py-for-loop")
            assert resp2.status_code == 200
            assert "common_error_patterns" not in resp2.json()

            assert len(_ENGINE_CACHE) == 1
            cached_engine_2, cached_factory_2 = next(iter(_ENGINE_CACHE.values()))
            assert cached_engine_1 is cached_engine_2
            assert cached_factory_1 is cached_factory_2
            assert real_get_session_factory(dev_settings) is cached_factory_1
    finally:
        clear_engine_cache()
        get_settings.cache_clear()


def test_question_authorization_anti_bypass_and_idempotency_conflict(
    seeded_client: TestClient,
) -> None:
    """Audit Item 2: Enforce question assignment authorization, initial_question_id role check, and idempotency conflict."""
    # 1. Forbid creating a session with a non-initial question (e.g., transfer_check or followup)
    bad_init_transfer = seeded_client.post(
        "/api/v1/sessions",
        json={
            "topic_id": "topic_py_for_loop",
            "learner_id": "learner_sec",
            "initial_question_id": "q_py_loop_transfer_01",
        },
    )
    assert bad_init_transfer.status_code == 400
    assert bad_init_transfer.json()["code"] == "DOMAIN_RULE_VIOLATION"

    bad_init_followup = seeded_client.post(
        "/api/v1/sessions",
        json={
            "topic_id": "topic_py_for_loop",
            "learner_id": "learner_sec",
            "initial_question_id": "q_py_loop_followup_01",
        },
    )
    assert bad_init_followup.status_code == 400
    assert bad_init_followup.json()["code"] == "DOMAIN_RULE_VIOLATION"

    # 2. Start a valid session (assigned q_py_loop_initial_01, status='active')
    sess = seeded_client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop", "learner_id": "learner_sec"},
    ).json()
    sess_id = sess["id"]
    assert sess["current_question_id"] == "q_py_loop_initial_01"

    # 3. Malicious bypass attempt: directly submitting transfer_check question in active session must be blocked (400)
    bypass_resp = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_transfer_01", "submitted_answer": "3 17"},
    )
    assert bypass_resp.status_code == 400
    assert bypass_resp.json()["code"] == "INVALID_SESSION_STATE"

    # 4. Submitting an unassigned practice or followup question in active session must also be blocked (400)
    unassigned_practice = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_practice_01", "submitted_answer": "6"},
    )
    assert unassigned_practice.status_code == 400
    assert unassigned_practice.json()["code"] == "INVALID_SESSION_STATE"

    # 5. Submit legitimate initial attempt with idempotency_key -> transitions session to 'diagnosing'
    valid_att = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={
            "question_id": "q_py_loop_initial_01",
            "submitted_answer": "4",
            "idempotency_key": "idem_auth_01",
        },
    )
    assert valid_att.status_code == 201
    att_id = valid_att.json()["attempt_id"]

    # 6. Re-sending the exact same request with the same idempotency_key succeeds (replays result even though session is now diagnosing)
    replay_att = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={
            "question_id": "q_py_loop_initial_01",
            "submitted_answer": "4",
            "idempotency_key": "idem_auth_01",
        },
    )
    assert replay_att.status_code == 201
    assert replay_att.json()["attempt_id"] == att_id

    # 7. Reusing the same idempotency_key with a DIFFERENT answer must raise 409 IDEMPOTENCY_CONFLICT
    conflict_att = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={
            "question_id": "q_py_loop_initial_01",
            "submitted_answer": "3",
            "idempotency_key": "idem_auth_01",
        },
    )
    assert conflict_att.status_code == 409
    assert conflict_att.json()["code"] == "IDEMPOTENCY_CONFLICT"

    # 8. Submitting a new attempt on q_py_loop_initial_01 without idempotency key while session is in 'diagnosing' is blocked
    repeat_initial = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "3"},
    )
    assert repeat_initial.status_code == 400
    assert repeat_initial.json()["code"] == "INVALID_SESSION_STATE"


def test_session_completion_semantics_distinguishes_ended_vs_mastered(
    seeded_client: TestClient,
) -> None:
    """Audit Item 3: Strictly distinguish session completed vs topic mastered (stable) vs transfer failed (needs_practice)."""
    sess = seeded_client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop", "learner_id": "learner_comp_sem"},
    ).json()
    sess_id = sess["id"]

    # A correct initial answer with reasoning authorizes transfer; direct skipping is forbidden.
    initial = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "3; each iteration adds the next value: 0, 1, 2."},
    )
    assert initial.status_code == 201
    assert initial.json()["next_action"] == "transfer_check"
    # Dispatch is now a safe recovery of the assigned, unanswered transfer item.
    disp = seeded_client.post(f"/api/v1/sessions/{sess_id}/transfer-check")
    assert disp.status_code == 200
    assert disp.json()["session_status"] == "transfer_checking"
    assigned_q_id = disp.json()["question"]["id"]
    assert assigned_q_id == "q_py_loop_transfer_01"

    # 1. Attempting to complete session in 'transfer_checking' BEFORE submitting any transfer attempt must fail (400)
    early_complete = seeded_client.post(f"/api/v1/sessions/{sess_id}/complete")
    assert early_complete.status_code == 400
    assert early_complete.json()["code"] == "INVALID_SESSION_STATE"

    # 2. Submit a WRONG transfer attempt ('3 15') -> KnowledgeState becomes 'needs_practice'
    fail_att = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/attempts",
        json={"question_id": assigned_q_id, "submitted_answer": "3 15"},
    )
    assert fail_att.status_code == 201
    assert fail_att.json()["is_correct"] is False
    assert fail_att.json()["knowledge_state_status"] == "needs_practice"

    # 3. Complete (end) the session after failed transfer check -> session is 'completed',
    #    but topic_mastered is False and knowledge_state_status remains 'needs_practice' (NEVER 'stable'!)
    comp_resp = seeded_client.post(
        f"/api/v1/sessions/{sess_id}/complete",
        json={"reason": "Learner ended session for today; will review tomorrow."},
    )
    assert comp_resp.status_code == 200
    comp_data = comp_resp.json()
    assert comp_data["status"] == "completed"
    assert comp_data["knowledge_state_status"] == "needs_practice"
    assert comp_data["topic_mastered"] is False

    # Verify profile endpoint also shows needs_practice, NOT stable
    ks_resp = seeded_client.get(
        "/api/v1/profile/knowledge-states?learner_id=learner_comp_sem"
    )
    assert ks_resp.status_code == 200
    ks_list = ks_resp.json()
    assert len(ks_list) == 1
    assert ks_list[0]["status"] == "needs_practice"


def test_model_provider_modes_demo_mock_labeling_and_ollama_without_api_key(
    seeded_client: TestClient,
    test_settings: Settings,
) -> None:
    """Audit Item 5: Verify Demo/Mock mode is explicitly labeled and Ollama does not require a remote API key."""
    from app.api.v1.dependencies import get_model_provider
    from app.model_provider import OllamaProvider

    # 1. Verify OllamaProvider resolution when allow_remote_model_calls=True and model_api_key=""
    ollama_settings = test_settings.model_copy(
        update={
            "app_env": "development",
            "model_provider": "ollama",
            "model_name": "qwen2.5-coder:7b",
            "model_api_key": "",
            "allow_remote_model_calls": True,
        }
    )
    provider = get_model_provider(ollama_settings)
    assert isinstance(provider, OllamaProvider)
    assert provider.provider_name == "ollama"
    assert provider.require_api_key is False
    assert provider.is_configured() is True

    # 2. Verify default dev/testing fallback uses FakeModelProvider with explicit mock/demo flags in API responses
    sess = seeded_client.post(
        "/api/v1/sessions",
        json={"topic_id": "topic_py_for_loop", "learner_id": "learner_mock_mode"},
    ).json()
    att = seeded_client.post(
        f"/api/v1/sessions/{sess['id']}/attempts",
        json={"question_id": "q_py_loop_initial_01", "submitted_answer": "4"},
    ).json()
    diag_id = att["diagnostic_case_id"]

    case_resp = seeded_client.get(f"/api/v1/diagnoses/{diag_id}")
    assert case_resp.status_code == 200
    case_data = case_resp.json()
    assert case_data["model_provider_name"] == "fake"
    assert case_data["is_mock_provider"] is True
    assert case_data["execution_mode"] == "mock"

    # Unscripted step in default FakeModelProvider uses explicit [DEMO/MOCK MODE] fallback
    step_resp = seeded_client.post(f"/api/v1/diagnoses/{diag_id}/step")
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["model_provider_name"] == "fake"
    assert step_data["is_mock_provider"] is True
    assert step_data["execution_mode"] == "mock"
    assert "DEMO/MOCK MODE" in (step_data["uncertainty_note"] or "")


def test_lifespan_raises_on_seed_failure_and_preserves_existing_data(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit Item 6: Verify lifespan does not silently swallow initialization errors and never overwrites existing data."""
    from pathlib import Path
    from app.api.v1.dependencies import clear_engine_cache
    import app.main as main_mod

    clear_engine_cache()
    db_file = Path(str(tmp_path)) / "lifespan_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ALLOW_REMOTE_MODEL_CALLS", "false")
    get_settings.cache_clear()
    dev_settings = get_settings()

    try:
        # 1. Normal startup migrates and seeds cleanly; create a learning session
        app1 = create_app(dev_settings)
        with TestClient(app1) as client1:
            s_resp = client1.post(
                "/api/v1/sessions",
                json={"topic_id": "topic_py_for_loop", "learner_id": "learner_persist"},
            )
            assert s_resp.status_code == 201
            created_session_id = s_resp.json()["id"]

        # 2. Second startup on the same DB preserves existing learner session without overwriting
        app2 = create_app(dev_settings)
        with TestClient(app2) as client2:
            get_resp = client2.get(f"/api/v1/sessions/{created_session_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["learner_id"] == "learner_persist"

        # 3. If import_content_pack raises a critical error, lifespan MUST re-raise (never silently ignore)
        def broken_seed(_session: Session) -> None:
            raise RuntimeError("Simulated critical content pack initialization failure")

        monkeypatch.setattr(main_mod, "import_content_pack", broken_seed)
        app_broken = create_app(dev_settings)
        with pytest.raises(RuntimeError, match="Simulated critical content pack initialization failure"):
            with TestClient(app_broken):
                pass
    finally:
        clear_engine_cache()
        get_settings.cache_clear()


def test_stage5c_real_session_http_smoke_with_isolated_sqlite_and_fake_provider(
    session_factory: sessionmaker[Session],
    test_settings: Settings,
) -> None:
    """Exercise the C1 browser flow through HTTP using isolated SQLite and an explicit offline model."""
    with transactional_session(session_factory) as session:
        import_content_pack(session)

    fake_provider = FakeModelProvider()
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_model_provider] = lambda: fake_provider

    with TestClient(app) as http:
        topics = http.get("/api/v1/topics")
        assert topics.status_code == 200
        assert any(topic["slug"] == "py-for-loop" for topic in topics.json())

        materials = http.get("/api/v1/topics/py-for-loop/materials")
        assert materials.status_code == 200
        assert materials.json()

        created = http.post(
            "/api/v1/sessions",
            json={"topic_id": "topic_py_for_loop", "learner_id": "stage5c_http_smoke"},
        )
        assert created.status_code == 201
        session_id = created.json()["id"]
        initial_question = created.json()["current_question"]
        assert initial_question["id"] == created.json()["current_question_id"]
        assert "standard_answer" not in initial_question

        loaded = http.get(f"/api/v1/sessions/{session_id}")
        assert loaded.status_code == 200
        assert loaded.json()["current_question"]["id"] == initial_question["id"]

        attempt = http.post(
            f"/api/v1/sessions/{session_id}/attempts",
            json={
                "question_id": initial_question["id"],
                "submitted_answer": "999, definitely incorrect",
                "idempotency_key": "stage5c-http-smoke-initial-1",
            },
        )
        assert attempt.status_code == 201
        result = attempt.json()
        assert result["attempt_id"]
        assert result["is_correct"] is False
        assert result["next_action"] == "diagnose"
        assert result["diagnostic_case_id"]

        case = http.get(f"/api/v1/diagnoses/{result['diagnostic_case_id']}")
        assert case.status_code == 200
        assert case.json()["is_mock_provider"] is True
        assert case.json()["execution_mode"] == "mock"

        updated = http.get(f"/api/v1/sessions/{session_id}")
        assert updated.status_code == 200
        assert updated.json()["status"] == "diagnosing"
        assert updated.json()["active_diagnostic_case_id"] == result["diagnostic_case_id"]


def test_openapi_schema_endpoint_inventory(seeded_client: TestClient) -> None:
    """Audit Item 7: Verify exact OpenAPI paths and HTTP operation counts vs hidden aliases."""
    openapi_resp = seeded_client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    schema = openapi_resp.json()
    paths = schema["paths"]

    # The skill-specific routes are public alongside shared APIs.
    assert len(paths) == 42
    assert "POST" in {method.upper() for method in paths["/api/v1/profile/evidence-revalidation"]}
    assert {
        "/api/v1/learner-model",
        "/api/v1/listening/lesson", "/api/v1/listening/sessions",
        "/api/v1/listening/sessions/{session_id}", "/api/v1/listening/sessions/{session_id}/submit",
        "/api/v1/listening/history",
        "/api/v1/writing/sessions", "/api/v1/writing/sessions/{session_id}/draft",
        "/api/v1/writing/sessions/{session_id}/revisions",
        "/api/v1/writing/sessions/{session_id}/revisions/{revision_id}",
        "/api/v1/speaking/prompts", "/api/v1/speaking/practices",
        "/api/v1/speaking/practices/{recording_id}",
    } <= set(paths)

    public_operations = [
        (method.upper(), path)
        for path, methods in paths.items()
        for method in methods
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(public_operations) == 46
    stage4_public_operations = [
        op for op in public_operations if op[1] != "/api/v1/health"
    ]
    assert len(stage4_public_operations) == 45

    # Hidden alias GET /api/v1/dashboard/summary is functional (200) but excluded from OpenAPI schema
    assert "/api/v1/dashboard/summary" not in paths
    alias_resp = seeded_client.get("/api/v1/dashboard/summary?learner_id=new_learner")
    assert alias_resp.status_code == 200
