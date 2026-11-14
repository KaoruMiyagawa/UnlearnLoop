"""Speaking practice metadata. Recordings are retained only in the browser."""

from datetime import datetime, timezone
from hashlib import sha256
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_db
from app.persistence.models import KnowledgeTopic, LearningSession, SpeakingPractice

router = APIRouter(prefix="/speaking", tags=["speaking"])
VERSION = "speaking-part1-v1"
TOPIC = "ielts-speaking-part1"
PROMPTS = {
    "daily-routine": "What part of your daily routine do you enjoy most, and why?",
    "study-place": "Where do you prefer to study, and what makes that place helpful?",
    "hobby": "What hobby would you like to spend more time on?",
}
Learner = Annotated[str, Query(min_length=1, max_length=64)]


class CompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    learner_id: str = Field(default="default_learner", min_length=1, max_length=64)
    recording_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    prompt_id: Literal["daily-routine", "study-place", "hobby"]
    prompt_version: Literal["speaking-part1-v1"]
    duration_seconds: float = Field(gt=0, le=600, allow_inf_nan=False)
    recorded_at: AwareDatetime
    self_check: list[Literal["direct", "detail", "pauses", "improvement"]] = Field(max_length=4)


def _session_id(learner: str) -> str:
    return "speak_" + sha256(f"{VERSION}:{learner}".encode()).hexdigest()[:40]


def _view(practice: SpeakingPractice) -> dict:
    def timestamp(value: datetime) -> str:
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()

    return {
        "recording_id": practice.recording_id, "session_id": practice.session_id,
        "prompt_id": practice.prompt_id, "prompt_version": practice.prompt_version,
        "prompt_text": practice.prompt_text, "duration_seconds": practice.duration_seconds,
        "recorded_at": timestamp(practice.recorded_at), "completed_at": timestamp(practice.completed_at),
        "self_check": practice.self_check, "evaluation_status": practice.evaluation_status,
        "evidence_type": practice.evidence_type,
        "note": "录音未上传。练习完成不证明口语水平、迁移或长期保持。",
    }


@router.get("/prompts")
def prompts():
    return [{"id": key, "text": value, "version": VERSION, "part": 1,
             "suggested_seconds": 30} for key, value in PROMPTS.items()]


@router.get("/practices")
def list_practices(learner_id: Learner = "default_learner", db: Session = Depends(get_db)):
    rows = db.scalars(select(SpeakingPractice).join(LearningSession).where(
        LearningSession.learner_id == learner_id,
    ).order_by(SpeakingPractice.completed_at.desc())).all()
    return [_view(row) for row in rows]


@router.post("/practices")
def complete_practice(payload: CompleteRequest, db: Session = Depends(get_db)):
    sid = _session_id(payload.learner_id)
    if len(set(payload.self_check)) != len(payload.self_check):
        raise HTTPException(422, "Self-check entries must be unique.")

    def replay(row: SpeakingPractice):
        recorded = row.recorded_at.replace(tzinfo=timezone.utc) if row.recorded_at.tzinfo is None else row.recorded_at
        if (row.session_id != sid or row.prompt_id != payload.prompt_id
                or row.prompt_version != payload.prompt_version
                or row.duration_seconds != payload.duration_seconds
                or recorded != payload.recorded_at or row.self_check != payload.self_check):
            raise HTTPException(409, "Recording ID already belongs to a different practice.")
        return _view(row)

    for attempt in range(2):
        existing = db.get(SpeakingPractice, payload.recording_id)
        if existing:
            return replay(existing)
        try:
            if db.get(KnowledgeTopic, TOPIC) is None:
                db.add(KnowledgeTopic(id=TOPIC, slug=TOPIC, domain_code="ielts_speaking",
                                      title="IELTS Speaking Part 1", summary="Original speaking practice"))
                db.flush()
            if db.get(LearningSession, sid) is None:
                db.add(LearningSession(id=sid, learner_id=payload.learner_id, topic_id=TOPIC,
                                       exam_spec_version=VERSION))
                db.flush()
            row = SpeakingPractice(
                recording_id=payload.recording_id, session_id=sid, prompt_id=payload.prompt_id,
                prompt_version=VERSION, prompt_text=PROMPTS[payload.prompt_id],
                duration_seconds=payload.duration_seconds, recorded_at=payload.recorded_at,
                self_check=payload.self_check,
            )
            db.add(row)
            db.commit()
            return _view(row)
        except IntegrityError:
            db.rollback()
            if attempt == 1:
                raise
    raise HTTPException(409, "Could not save practice metadata.")


@router.delete("/practices/{recording_id}")
def delete_practice(recording_id: str, learner_id: Learner = "default_learner", db: Session = Depends(get_db)):
    row = db.scalar(select(SpeakingPractice).join(LearningSession).where(
        SpeakingPractice.recording_id == recording_id, LearningSession.learner_id == learner_id,
    ))
    if row is None:
        raise HTTPException(404, "Practice metadata was not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True}
