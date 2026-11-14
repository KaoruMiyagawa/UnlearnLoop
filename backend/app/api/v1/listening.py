"""One versioned, authored listening lesson backed by shared learning history."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_db
from app.persistence.models import Attempt, KnowledgeTopic, LearningSession, Question

router = APIRouter(prefix="/listening", tags=["listening"])
CONTENT_VERSION = "listening-study-group-v1"
RULE_VERSION = "listening-exact-choice-v1"
TOPIC_ID = "ielts-listening-study-group"
AUDIO_URL = "/audio/listening/study-group.wav"
LESSON: dict[str, Any] = {
    "id": "study-group-workshop", "title": "A study skills workshop", "scenario": "A student support officer calls to confirm workshop arrangements.",
    "duration_seconds": 64, "audio_url": AUDIO_URL, "content_version": CONTENT_VERSION,
    "evaluation_rule_version": RULE_VERSION, "evaluation_source": "rule_check",
    "audio_source": "Original script authored for VerbaTrail and synthesized offline with Piper 1.8.0 using the en_US-joe-medium voice at rhasspy/piper-voices commit 2f358b6a560e3a913ebf509b2f3344f20b367f94.",
    "rights": "Original VerbaTrail text; voice card and upstream voice-chain use list identify CC0 training data (rdh base and joe recordings). Voice model is not bundled. No IELTS source audio or material used.",
    "questions": [
        {"prompt": "Which room will the workshop use?", "options": ["Room 12", "Room 24", "Room 42"], "answer": "Room 24", "explanation": "The caller says the original room 12 is unavailable and confirms room 24.", "start": 9.24, "end": 17.39},
        {"prompt": "Which entrance should students use?", "options": ["The north entrance", "The west door", "The main reception"], "answer": "The west door", "explanation": "The west door is identified by the bicycle racks.", "start": 17.51, "end": 21.73},
        {"prompt": "What time does the workshop begin?", "options": ["10:15", "10:50", "11:15"], "answer": "10:15", "explanation": "The start time is spoken as ten fifteen.", "start": 21.85, "end": 26.55},
        {"prompt": "What should students bring?", "options": ["A student card and a notebook", "A printed reading pack", "A laptop and headphones"], "answer": "A student card and a notebook", "explanation": "The caller asks students to bring their student card and a notebook; the pack is provided there.", "start": 26.67, "end": 29.14},
        {"prompt": "By when should a student email if they cannot attend?", "options": ["Before Tuesday afternoon", "By Wednesday morning", "Before Thursday"], "answer": "Before Tuesday afternoon", "explanation": "Email before Tuesday afternoon so the place can be offered to someone on the waiting list.", "start": 34.30, "end": 41.69},
    ],
}

class StartRequest(BaseModel):
    learner_id: str = Field(default="default_learner", max_length=64)

class SubmitRequest(BaseModel):
    answers: dict[str, str] = Field(min_length=5, max_length=5)
    idempotency_key: str = Field(min_length=8, max_length=100)

def _public_question(index: int, reveal: bool = False) -> dict[str, Any]:
    item = LESSON["questions"][index]
    result = {"id": f"{CONTENT_VERSION}-q{index + 1}", "prompt": item["prompt"], "options": item["options"], "number": index + 1}
    if reveal:
        result.update({"correct_answer": item["answer"], "explanation": item["explanation"], "start_seconds": item["start"], "end_seconds": item["end"]})
    return result

def _attempts(db: Session, session_id: str) -> list[Attempt]:
    return list(db.scalars(select(Attempt).where(Attempt.session_id == session_id).order_by(Attempt.question_id)).all())

def _view(db: Session, session: LearningSession) -> dict[str, Any]:
    attempts = _attempts(db, session.id)
    completed = len(attempts) == len(LESSON["questions"])
    result: dict[str, Any] = {
        "session_id": session.id, "status": "completed" if completed else session.status,
        "lesson": {k: v for k, v in LESSON.items() if k != "questions"} | {"questions": [_public_question(i, completed) for i in range(5)]},
        "answers": {a.question_id: a.submitted_answer for a in attempts},
    }
    if completed:
        result["score"] = sum(bool(a.is_correct) for a in attempts)
        result["results"] = [{"question": _public_question(i, True), "submitted_answer": attempts[i].submitted_answer, "is_correct": bool(attempts[i].is_correct)} for i in range(5)]
        result["assessment_note"] = "本次练习结果，仅代表这次原创听力任务表现；不构成 IELTS Band 分数或长期能力评估。"
    return result

@router.get("/lesson")
def get_lesson() -> dict[str, Any]:
    return {k: v for k, v in LESSON.items() if k != "questions"} | {"questions": [_public_question(i) for i in range(5)]}

@router.post("/sessions", status_code=201)
def start_session(payload: StartRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    topic = db.get(KnowledgeTopic, TOPIC_ID)
    if topic is None:
        topic = KnowledgeTopic(id=TOPIC_ID, slug=TOPIC_ID, domain_code="ielts_listening", title=LESSON["title"], summary=LESSON["scenario"], difficulty_level=1)
        db.add(topic)
        db.flush()
    session = LearningSession(learner_id=payload.learner_id, topic_id=TOPIC_ID, exam_spec_version=CONTENT_VERSION)
    db.add(session)
    db.flush()
    for index, item in enumerate(LESSON["questions"]):
        qid = f"{CONTENT_VERSION}-q{index + 1}"
        question = db.get(Question, qid)
        if question is None:
            question = Question(id=qid, topic_id=TOPIC_ID, question_role="initial", question_type="multiple_choice", prompt_text=item["prompt"], context_snippet=None, standard_answer=item["answer"], answer_explanation=item["explanation"], evaluation_rubric={"rule_version": RULE_VERSION, "options": item["options"], "audio_start": item["start"], "audio_end": item["end"], "audio_url": AUDIO_URL}, difficulty=1, version=1)
            db.add(question)
    return _view(db, session)

@router.get("/sessions/{session_id}")
def get_session(session_id: str, learner_id: str = Query(default="default_learner", min_length=1, max_length=64), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.get(LearningSession, session_id)
    if session is None or session.learner_id != learner_id or session.exam_spec_version != CONTENT_VERSION or session.topic_id != TOPIC_ID:
        raise HTTPException(404, "Listening session was not found.")
    return _view(db, session)

@router.post("/sessions/{session_id}/submit")
def submit_session(session_id: str, payload: SubmitRequest, learner_id: str = Query(default="default_learner", min_length=1, max_length=64), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.get(LearningSession, session_id)
    if session is None or session.learner_id != learner_id or session.exam_spec_version != CONTENT_VERSION or session.topic_id != TOPIC_ID:
        raise HTTPException(404, "Listening session was not found.")
    if payload.idempotency_key != f"listen-{session_id}":
        raise HTTPException(422, "The idempotency key does not match this listening session.")
    prior = _attempts(db, session_id)
    if prior:
        if len(prior) != 5 or any(payload.answers.get(a.question_id) != a.submitted_answer for a in prior):
            raise HTTPException(409, "This listening session has already been submitted with different answers.")
        return _view(db, session)
    if session.status in ("completed", "paused"):
        raise HTTPException(409, "This listening session is no longer active.")
    expected = {f"{CONTENT_VERSION}-q{i + 1}" for i in range(5)}
    if set(payload.answers) != expected:
        raise HTTPException(422, "Provide one answer for each listening question.")
    for index, item in enumerate(LESSON["questions"]):
        qid = f"{CONTENT_VERSION}-q{index + 1}"
        question = db.get(Question, qid)
        answer = payload.answers[qid]
        if answer not in item["options"]:
            raise HTTPException(422, f"Answer for question {index + 1} is not a listed option.")
        correct = answer == item["answer"]
        db.add(Attempt(session_id=session_id, question_id=qid, question_version=1, question_snapshot_json={"question_type": "multiple_choice", "content_version": CONTENT_VERSION, "rule_version": RULE_VERSION, "audio_url": AUDIO_URL, "audio_start": item["start"], "audio_end": item["end"], "explanation": item["explanation"], "source": LESSON["rights"]}, item_evaluation_json={"evaluation_source": "rule_check", "rule_version": RULE_VERSION, "outcome": "correct" if correct else "incorrect"}, attempt_role="initial", submitted_answer=answer, evaluation_rule_version=RULE_VERSION, is_correct=correct, evaluation_status="evaluated", evaluation_summary="Correct" if correct else "Review the highlighted audio segment.", idempotency_key=f"{payload.idempotency_key}:{index + 1}"))
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    session.updated_at = datetime.now(timezone.utc)
    db.flush()
    return _view(db, session)

@router.get("/history")
def history(learner_id: str = "default_learner", db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    sessions = db.scalars(select(LearningSession).where(LearningSession.learner_id == learner_id, LearningSession.topic_id == TOPIC_ID).order_by(LearningSession.started_at.desc())).all()
    return [{"session_id": s.id, "started_at": s.started_at.isoformat(), "completed_at": s.completed_at.isoformat() if s.completed_at else None, "status": "completed" if len(_attempts(db, s.id)) == 5 else s.status, "score": sum(bool(a.is_correct) for a in _attempts(db, s.id)) if len(_attempts(db, s.id)) == 5 else None} for s in sessions]
