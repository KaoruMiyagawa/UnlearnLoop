"""API router for knowledge topics, learning materials, and sanitized questions."""

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_learning_service
from app.api.v1.schemas import (
    LearningMaterialResponse,
    SanitizedQuestionResponse,
    TopicDetailResponse,
    TopicSummaryResponse,
)
from app.application.learning_service import LearningAppService

router = APIRouter(tags=["topics"])


@router.get(
    "/topics",
    response_model=list[TopicSummaryResponse],
    summary="List knowledge topics",
)
def list_topics(
    domain_code: str | None = Query(default=None, description="Optional domain filter (e.g., 'python')."),
    service: LearningAppService = Depends(get_learning_service),
) -> list[TopicSummaryResponse]:
    """Retrieve catalog of knowledge topics and their prerequisite dependency IDs."""
    return service.list_topics(domain_code=domain_code)


@router.get(
    "/topics/{topic_id_or_slug}",
    response_model=TopicDetailResponse,
    summary="Get knowledge topic detail",
)
def get_topic_detail(
    topic_id_or_slug: str,
    service: LearningAppService = Depends(get_learning_service),
) -> TopicDetailResponse:
    """Retrieve detailed topic information including prerequisites and learning materials."""
    return service.get_topic_detail(topic_id_or_slug)


@router.get(
    "/topics/{topic_id_or_slug}/materials",
    response_model=list[LearningMaterialResponse],
    summary="Get topic learning materials",
)
def get_topic_materials(
    topic_id_or_slug: str,
    service: LearningAppService = Depends(get_learning_service),
) -> list[LearningMaterialResponse]:
    """Retrieve reading materials associated with a knowledge topic."""
    return service.get_topic_materials(topic_id_or_slug)


@router.get(
    "/questions/{question_id}",
    response_model=SanitizedQuestionResponse,
    summary="Get sanitized question",
)
def get_sanitized_question(
    question_id: str,
    service: LearningAppService = Depends(get_learning_service),
) -> SanitizedQuestionResponse:
    """Retrieve a playable question sanitized to ensure standard answers are never leaked."""
    return service.get_sanitized_question(question_id)
