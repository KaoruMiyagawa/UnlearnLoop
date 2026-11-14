"""Original Task 2 practice with versioned drafts and formal submissions."""

from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_db
from app.persistence.models import KnowledgeTopic, LearningSession, WritingDraft, WritingRevision, utc_now

router = APIRouter(prefix="/writing", tags=["writing"])
TOPIC_ID = "ielts-writing-task-2-shared-spaces"
LEARNER = "default_learner"
MAX_LENGTH = 20000
WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")


class Task(BaseModel):
    version: str
    title: str
    prompt: str
    instruction: str
    suggested_words: int
    max_characters: int
    checklist: list[str]


TASK = Task(
    version="writing-shared-spaces-v1",
    title="Shared spaces for neighbourhoods",
    prompt=(
        "Some local councils turn unused land into community gardens, while others use it "
        "for outdoor sports facilities. Discuss both views and give your own opinion."
    ),
    instruction="Give reasons for your answer and include relevant examples from your knowledge or experience.",
    suggested_words=250,
    max_characters=MAX_LENGTH,
    checklist=[
        "我是否分别解释了社区花园和户外运动设施各自的价值？",
        "我的观点是否清楚，理由和例子是否直接支持它？",
        "每段是否围绕一个清楚的重点展开？",
        "我是否通读了全文并检查容易混淆的措辞和句子？",
    ],
)


class OpenRequest(BaseModel):
    learner_id: str = Field(default=LEARNER, min_length=1, max_length=64)


class DraftInput(BaseModel):
    body: str = Field(max_length=MAX_LENGTH)
    version: int = Field(ge=0, le=2147483646)

    @field_validator("body")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if any(ord(c) < 32 and c not in "\t\n\r" or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("Only plain Unicode text and standard whitespace are supported.")
        return value.replace("\r\n", "\n").replace("\r", "\n")


class SubmitInput(DraftInput):
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class DraftView(BaseModel):
    body: str
    version: int
    updated_at: AwareDatetime


class Feedback(BaseModel):
    method: Literal["deterministic_text_metrics"] = "deterministic_text_metrics"
    rule_version: Literal["writing-text-metrics-v1"] = "writing-text-metrics-v1"
    confidence: Literal["observable_text_only"] = "observable_text_only"
    semantic_quality: Literal["not_assessed"] = "not_assessed"
    word_count: int
    below_suggested_words: bool
    paragraph_blocks: int
    word_count_change: int | None


class RevisionSummary(BaseModel):
    id: str
    number: int
    source_revision_id: str | None
    submitted_at: AwareDatetime
    feedback: Feedback


class RevisionView(RevisionSummary):
    body: str


class SessionView(BaseModel):
    session_id: str
    task: Task
    draft: DraftView
    revisions: list[RevisionSummary]


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _draft_view(draft: WritingDraft) -> DraftView:
    return DraftView(body=draft.body, version=draft.version, updated_at=_utc(draft.updated_at))


def _revision_summary(revision: WritingRevision) -> RevisionSummary:
    return RevisionSummary(
        id=revision.id, number=revision.number, source_revision_id=revision.source_revision_id,
        submitted_at=_utc(revision.submitted_at), feedback=Feedback.model_validate(revision.feedback),
    )


def _revision_view(revision: WritingRevision) -> RevisionView:
    return RevisionView(**_revision_summary(revision).model_dump(), body=revision.body)


def _owned_draft(db: Session, session_id: str, learner_id: str) -> WritingDraft:
    draft = db.scalar(select(WritingDraft).join(LearningSession).where(
        WritingDraft.session_id == session_id, LearningSession.learner_id == learner_id,
    ))
    if draft is None:
        raise HTTPException(404, "Writing session was not found.")
    return draft


def _session_id(learner_id: str) -> str:
    return "writ_" + sha256(f"{TASK.version}:{learner_id}".encode()).hexdigest()[:40]


def _advance_draft(db: Session, draft: WritingDraft, payload: DraftInput) -> int:
    return db.execute(update(WritingDraft).where(
        WritingDraft.session_id == draft.session_id, WritingDraft.version == payload.version,
    ).values(body=payload.body, version=payload.version + 1, updated_at=utc_now())).rowcount


@router.post("/sessions")
def open_session(payload: OpenRequest, db: Session = Depends(get_db)) -> SessionView:
    session_id = _session_id(payload.learner_id)
    draft = db.get(WritingDraft, session_id)
    # Concurrent opens can race on either the shared topic or the deterministic session ID.
    for attempt in range(2):
        if draft is not None:
            break
        try:
            if db.get(KnowledgeTopic, TOPIC_ID) is None:
                db.add(KnowledgeTopic(id=TOPIC_ID, slug=TOPIC_ID, domain_code="ielts_writing",
                                      title="IELTS Writing Task 2", summary=TASK.title))
                db.flush()
            db.add(LearningSession(id=session_id, learner_id=payload.learner_id,
                                   topic_id=TOPIC_ID, exam_spec_version=TASK.version))
            db.flush()
            draft = WritingDraft(session_id=session_id, task_snapshot=TASK.model_dump())
            db.add(draft)
            db.commit()
        except IntegrityError:
            db.rollback()
            draft = db.get(WritingDraft, session_id)
            if draft is None and attempt == 1:
                raise

    rows = db.scalars(select(WritingRevision).where(WritingRevision.session_id == session_id)
                      .order_by(WritingRevision.number.desc()))
    return SessionView(
        session_id=session_id, task=Task.model_validate(draft.task_snapshot), draft=_draft_view(draft),
        revisions=[_revision_summary(row) for row in rows],
    )


LearnerQuery = Annotated[str, Query(min_length=1, max_length=64)]


@router.put("/sessions/{session_id}/draft")
def save_draft(
    session_id: str, payload: DraftInput, db: Session = Depends(get_db), learner_id: LearnerQuery = LEARNER,
) -> DraftView:
    draft = _owned_draft(db, session_id, learner_id)
    if payload.body == draft.body:
        return _draft_view(draft)
    if not _advance_draft(db, draft, payload):
        raise HTTPException(409, "The saved draft changed. Reload or review the latest text before saving.")
    db.refresh(draft)
    db.commit()
    return _draft_view(draft)


@router.post("/sessions/{session_id}/revisions")
def submit_revision(
    session_id: str, payload: SubmitInput, db: Session = Depends(get_db), learner_id: LearnerQuery = LEARNER,
) -> RevisionView:
    draft = _owned_draft(db, session_id, learner_id)
    words = len(WORD.findall(payload.body))
    if not words:
        raise HTTPException(422, "Enter some essay text before submitting.")

    prior_query = select(WritingRevision).where(
        WritingRevision.session_id == session_id, WritingRevision.idempotency_key == payload.idempotency_key,
    )

    def replay(prior: WritingRevision) -> RevisionView:
        if prior.body != payload.body or prior.base_version != payload.version:
            raise HTTPException(409, "This submission key has already been used for a different request.")
        return _revision_view(prior)

    if prior := db.scalar(prior_query):
        return replay(prior)
    if not _advance_draft(db, draft, payload):
        if prior := db.scalar(prior_query):
            return replay(prior)
        raise HTTPException(409, "The saved draft changed. Review the latest text before submitting.")

    latest = db.scalar(select(WritingRevision).where(WritingRevision.session_id == session_id)
                       .order_by(WritingRevision.number.desc()).limit(1))
    if latest and latest.body == payload.body:
        raise HTTPException(409, "Edit the essay before submitting another revision.")
    feedback = Feedback(
        word_count=words, below_suggested_words=words < draft.task_snapshot["suggested_words"],
        paragraph_blocks=sum(bool(block.strip()) for block in re.split(r"\n[^\S\n]*\n", payload.body)),
        word_count_change=words - latest.feedback["word_count"] if latest else None,
    )
    revision = WritingRevision(
        session_id=session_id, number=latest.number + 1 if latest else 1,
        source_revision_id=latest.id if latest else None, body=payload.body, base_version=payload.version,
        idempotency_key=payload.idempotency_key, feedback=feedback.model_dump(),
    )
    db.add(revision)
    session = db.get(LearningSession, session_id)
    if session.completed_at is None:
        session.status = "completed"
        session.completed_at = utc_now()
    db.commit()
    return _revision_view(revision)


@router.get("/sessions/{session_id}/revisions/{revision_id}")
def get_revision(
    session_id: str, revision_id: str, db: Session = Depends(get_db), learner_id: LearnerQuery = LEARNER,
) -> RevisionView:
    _owned_draft(db, session_id, learner_id)
    revision = db.get(WritingRevision, revision_id)
    if revision is None or revision.session_id != session_id:
        raise HTTPException(404, "Writing revision was not found.")
    return _revision_view(revision)
