"""IELTS exam catalogue and persisted preparation goal endpoints."""

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_exam_profile_service
from app.api.v1.schemas import (
    ExamCatalogEntryResponse,
    ExamPreparationProfileResponse,
    ExamPreparationProfileUpdate,
)
from app.application.exam_profile_service import ExamProfileService

router = APIRouter(tags=["exams"])


@router.get("/exams/catalog", response_model=list[ExamCatalogEntryResponse])
def list_exam_catalog(
    service: ExamProfileService = Depends(get_exam_profile_service),
) -> list[ExamCatalogEntryResponse]:
    return service.list_catalog()


@router.get("/profile/exam-preparation", response_model=ExamPreparationProfileResponse)
def get_exam_preparation_profile(
    learner_id: str = Query(default="default_learner", min_length=1, max_length=64),
    service: ExamProfileService = Depends(get_exam_profile_service),
) -> ExamPreparationProfileResponse:
    return service.get_profile(learner_id)


@router.put("/profile/exam-preparation", response_model=ExamPreparationProfileResponse)
def update_exam_preparation_profile(
    payload: ExamPreparationProfileUpdate,
    learner_id: str = Query(default="default_learner", min_length=1, max_length=64),
    service: ExamProfileService = Depends(get_exam_profile_service),
) -> ExamPreparationProfileResponse:
    return service.update_profile(learner_id, payload)
