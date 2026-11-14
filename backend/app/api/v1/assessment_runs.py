"""Persist assessment runs; learner IDs are development scoping, not authentication."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.v1.dependencies import get_db
from app.persistence.models import AssessmentRun, AssessmentTask

router = APIRouter(prefix="/assessment-runs", tags=["assessment"])
SKILLS = ("listening", "speaking", "reading", "writing")


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    learner_id: str = Field(default="default_learner", min_length=1, max_length=64)
    assessment_version: str = Field(default="initial-v1", min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("learner_id", "assessment_version", "idempotency_key")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must not be blank")
        return value


class TaskView(BaseModel):
    skill_id: Literal["listening", "speaking", "reading", "writing"]
    status: Literal["not_started", "in_progress", "skipped", "completed"]
    evidence_source: str | None
    evidence_reference: str | None


class RunView(BaseModel):
    run_id: str
    learner_id: str
    assessment_version: str
    status: Literal["in_progress", "completed"]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    tasks: list[TaskView]

    @field_validator("created_at", "updated_at", "completed_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def view(run: AssessmentRun) -> RunView:
    tasks = {task.skill_id: task for task in run.tasks}
    return RunView(run_id=run.id, learner_id=run.learner_id, assessment_version=run.assessment_version,
                   status=run.status, created_at=run.created_at, updated_at=run.updated_at,
                   completed_at=run.completed_at, tasks=[TaskView(skill_id=s, status=tasks[s].status,
                   evidence_source=tasks[s].evidence_source, evidence_reference=tasks[s].evidence_reference) for s in SKILLS])


def find_key(db: Session, learner_id: str, key: str) -> AssessmentRun | None:
    return db.scalar(select(AssessmentRun).options(selectinload(AssessmentRun.tasks)).where(
        AssessmentRun.learner_id == learner_id, AssessmentRun.idempotency_key == key))


def replay(run: AssessmentRun, payload: CreateRun) -> RunView:
    if run.assessment_version != payload.assessment_version:
        raise HTTPException(status_code=409, detail="Idempotency key was used for a different request.")
    return view(run)


@router.post("", response_model=RunView)
def create_run(payload: CreateRun, db: Session = Depends(get_db)) -> RunView:
    if prior := find_key(db, payload.learner_id, payload.idempotency_key):
        return replay(prior, payload)
    run = AssessmentRun(learner_id=payload.learner_id, assessment_version=payload.assessment_version,
                        idempotency_key=payload.idempotency_key,
                        tasks=[AssessmentTask(skill_id=skill) for skill in SKILLS])
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = find_key(db, payload.learner_id, payload.idempotency_key)
        if prior is None:
            raise
        return replay(prior, payload)
    return view(run)


@router.get("", response_model=list[RunView])
def list_runs(learner_id: str = Query(default="default_learner", min_length=1, max_length=64),
              db: Session = Depends(get_db)) -> list[RunView]:
    runs = db.scalars(select(AssessmentRun).options(selectinload(AssessmentRun.tasks)).where(
        AssessmentRun.learner_id == learner_id).order_by(AssessmentRun.created_at.desc(), AssessmentRun.id.desc())).all()
    return [view(run) for run in runs]


@router.get("/{run_id}", response_model=RunView)
def get_run(run_id: str, learner_id: str = Query(default="default_learner", min_length=1, max_length=64),
            db: Session = Depends(get_db)) -> RunView:
    run = db.scalar(select(AssessmentRun).options(selectinload(AssessmentRun.tasks)).where(
        AssessmentRun.id == run_id, AssessmentRun.learner_id == learner_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Assessment run was not found.")
    return view(run)
