"""API router for learning sessions, attempts, and transfer check dispatch."""

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.dependencies import get_learning_service
from app.api.v1.schemas import (
    AttemptDetailResponse,
    AttemptResultResponse,
    AttemptSummaryResponse,
    CreateSessionRequest,
    DispatchTransferRequest,
    SessionActionRequest,
    SessionDetailResponse,
    SessionSummaryResponse,
    LearningMaterialResponse,
    SubmitAttemptRequest,
    TransferCheckDispatchResponse,
)
from app.application.learning_service import LearningAppService

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    response_model=SessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a learning session",
)
def create_session(
    payload: CreateSessionRequest,
    service: LearningAppService = Depends(get_learning_service),
) -> SessionDetailResponse:
    """Start a new learning session on a topic, initializing with its first question."""
    return service.create_session(
        topic_id=payload.topic_id,
        learner_id=payload.learner_id,
        initial_question_id=payload.initial_question_id,
        exam_variant=payload.exam_variant,
        question_type=payload.question_type,
    )


@router.get(
    "/sessions",
    response_model=list[SessionSummaryResponse],
    summary="List learning sessions",
)
def list_sessions(
    learner_id: str = Query(default="default_learner", description="Learner ID filter."),
    session_status: str | None = Query(default=None, alias="status", description="Optional status filter."),
    service: LearningAppService = Depends(get_learning_service),
) -> list[SessionSummaryResponse]:
    """Retrieve historical and active sessions for a learner."""
    return service.list_sessions(learner_id=learner_id, status=session_status)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetailResponse,
    summary="Get learning session detail",
)
def get_session(
    session_id: str,
    service: LearningAppService = Depends(get_learning_service),
) -> SessionDetailResponse:
    """Retrieve current state of a learning session, current question, and diagnostic pointers."""
    return service.get_session_detail(session_id)


@router.get("/sessions/{session_id}/material", response_model=LearningMaterialResponse | None)
def get_current_session_material(
    session_id: str,
    service: LearningAppService = Depends(get_learning_service),
) -> LearningMaterialResponse | None:
    """Expose only the material of the question currently assigned to this session."""
    return service.get_current_session_material(session_id)


@router.post(
    "/sessions/{session_id}/pause",
    response_model=SessionDetailResponse,
    summary="Pause learning session",
)
def pause_session(
    session_id: str,
    payload: SessionActionRequest | None = None,
    service: LearningAppService = Depends(get_learning_service),
) -> SessionDetailResponse:
    """Pause an active or diagnosing learning session."""
    reason = payload.reason if payload else None
    return service.pause_session(session_id, reason=reason)


@router.post(
    "/sessions/{session_id}/resume",
    response_model=SessionDetailResponse,
    summary="Resume learning session",
)
def resume_session(
    session_id: str,
    payload: SessionActionRequest | None = None,
    service: LearningAppService = Depends(get_learning_service),
) -> SessionDetailResponse:
    """Resume a paused learning session back to active or diagnosing status."""
    reason = payload.reason if payload else None
    return service.resume_session(session_id, reason=reason)


@router.post(
    "/sessions/{session_id}/complete",
    response_model=SessionDetailResponse,
    summary="Complete learning session",
)
def complete_session(
    session_id: str,
    payload: SessionActionRequest | None = None,
    service: LearningAppService = Depends(get_learning_service),
) -> SessionDetailResponse:
    """Complete a learning session following successful transfer checking."""
    reason = payload.reason if payload else None
    return service.complete_session(session_id, reason=reason)


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/attempts",
    response_model=AttemptResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an answer attempt",
)
def submit_attempt(
    session_id: str,
    payload: SubmitAttemptRequest,
    service: LearningAppService = Depends(get_learning_service),
) -> AttemptResultResponse:
    """Submit an answer to the current question, evaluate rules, and trigger diagnostic state transitions."""
    return service.submit_attempt(
        session_id=session_id,
        question_id=payload.question_id,
        submitted_answer=payload.submitted_answer,
        structured_answer=payload.structured_answer,
        group_version_id=payload.group_version_id,
        idempotency_key=payload.idempotency_key,
    )


@router.get(
    "/sessions/{session_id}/attempts",
    response_model=list[AttemptSummaryResponse],
    summary="List attempts for session",
)
def list_session_attempts(
    session_id: str,
    service: LearningAppService = Depends(get_learning_service),
) -> list[AttemptSummaryResponse]:
    """Retrieve all attempt history recorded within a session."""
    return service.list_attempts_for_session(session_id)


@router.get(
    "/attempts/{attempt_id}",
    response_model=AttemptDetailResponse,
    summary="Get attempt detail",
)
def get_attempt_detail(
    attempt_id: str,
    service: LearningAppService = Depends(get_learning_service),
) -> AttemptDetailResponse:
    """Retrieve immutable record and snapshot of an attempt."""
    return service.get_attempt_detail(attempt_id)


# ---------------------------------------------------------------------------
# Transfer Check Dispatch
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/transfer-check",
    response_model=TransferCheckDispatchResponse,
    summary="Dispatch transfer verification question",
)
def dispatch_transfer_check(
    session_id: str,
    payload: DispatchTransferRequest | None = None,
    service: LearningAppService = Depends(get_learning_service),
) -> TransferCheckDispatchResponse:
    """Dispatch an independent, fresh transfer verification question to verify mastery."""
    force_fresh = payload.force_fresh if payload else True
    return service.dispatch_transfer_question(session_id, force_fresh=force_fresh)
