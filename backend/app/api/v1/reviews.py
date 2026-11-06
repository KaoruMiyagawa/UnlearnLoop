"""API router for spaced review tasks."""

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_learning_service
from app.api.v1.schemas import CompleteReviewRequest, ReviewItemResponse
from app.application.learning_service import LearningAppService

router = APIRouter(tags=["reviews"])


@router.get(
    "/reviews",
    response_model=list[ReviewItemResponse],
    summary="List scheduled review items",
)
def list_reviews(
    learner_id: str = Query(default="default_learner", description="Learner ID filter."),
    review_status: str = Query(default="pending", alias="status", description="Status filter ('pending' or 'completed')."),
    service: LearningAppService = Depends(get_learning_service),
) -> list[ReviewItemResponse]:
    """Retrieve scheduled review tasks triggered by failed attempts or diagnosis degradations."""
    return service.list_reviews(learner_id=learner_id, status=review_status)


@router.post(
    "/reviews/{review_id}/complete",
    response_model=ReviewItemResponse,
    summary="Complete a scheduled review task",
)
def complete_review(
    review_id: str,
    payload: CompleteReviewRequest | None = None,
    service: LearningAppService = Depends(get_learning_service),
) -> ReviewItemResponse:
    """Mark a scheduled review task as completed, recording optional tutor/learner review notes."""
    review_notes = payload.review_notes if payload else None
    return service.complete_review(review_id, review_notes=review_notes)
