"""Root router for /api/v1 endpoints."""

from fastapi import APIRouter

from app.api.v1.diagnoses import router as diagnoses_router
from app.api.v1.exams import router as exams_router
from app.api.v1.listening import router as listening_router
from app.api.v1.health import router as health_router
from app.api.v1.profile import router as profile_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.topics import router as topics_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(topics_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(diagnoses_router)
api_v1_router.include_router(reviews_router)
api_v1_router.include_router(profile_router)
api_v1_router.include_router(exams_router)
api_v1_router.include_router(listening_router)
