"""API router for learner profile, knowledge mastery states, and dashboard summary."""

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_learning_service
from app.api.v1.schemas import (
    DashboardSummaryResponse, EvidenceRevalidationRequest, EvidenceRevalidationResponse,
    KnowledgeStateResponse, LearningHistoryEventResponse,
)
from app.application.learning_service import LearningAppService

router = APIRouter(tags=["profile"])


@router.post(
    "/profile/evidence-revalidation",
    response_model=EvidenceRevalidationResponse,
    summary="Start a fresh learning session to revalidate affected evidence",
)
def start_evidence_revalidation(
    payload: EvidenceRevalidationRequest,
    service: LearningAppService = Depends(get_learning_service),
) -> EvidenceRevalidationResponse:
    return service.start_evidence_revalidation(payload)


@router.get(
    "/profile/history",
    response_model=list[LearningHistoryEventResponse],
    summary="Get a learner-safe learning history timeline",
)
def list_learning_history(
    learner_id: str = Query(default="default_learner", description="Learner ID."),
    limit: int = Query(default=100, ge=1, le=200),
    service: LearningAppService = Depends(get_learning_service),
) -> list[LearningHistoryEventResponse]:
    return service.list_learning_history(learner_id=learner_id, limit=limit)


@router.get(
    "/profile/knowledge-states",
    response_model=list[KnowledgeStateResponse],
    summary="List knowledge mastery states",
)
def list_knowledge_states(
    learner_id: str = Query(default="default_learner", description="Learner ID."),
    service: LearningAppService = Depends(get_learning_service),
) -> list[KnowledgeStateResponse]:
    """Retrieve operational knowledge mastery states, confidence scores, and unresolved error codes."""
    return service.list_knowledge_states(learner_id=learner_id)


@router.get(
    "/profile/summary",
    response_model=DashboardSummaryResponse,
    summary="Get learning dashboard summary",
)
def get_profile_summary(
    learner_id: str = Query(default="default_learner", description="Learner ID."),
    service: LearningAppService = Depends(get_learning_service),
) -> DashboardSummaryResponse:
    """Retrieve aggregated counts of active/completed sessions, attempts, pending reviews, and mastered topics."""
    return service.get_dashboard_summary(learner_id=learner_id)


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
    summary="Get dashboard summary (alias)",
    include_in_schema=False,
)
def get_dashboard_summary_alias(
    learner_id: str = Query(default="default_learner", description="Learner ID."),
    service: LearningAppService = Depends(get_learning_service),
) -> DashboardSummaryResponse:
    return service.get_dashboard_summary(learner_id=learner_id)
