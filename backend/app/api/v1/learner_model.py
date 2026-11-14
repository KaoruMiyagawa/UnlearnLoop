"""Read-only projection of existing learning records; no inferred band scores."""
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_db
from app.application.evidence_validity import evidence_status
from app.persistence.models import (Attempt, ExamPreparationProfile, KnowledgeTopic, LearningSession,
    ReadingGroupVersion, ReviewItem, SpeakingPractice, WritingDraft, WritingRevision)

router = APIRouter(tags=["learner-model"])


class Evidence(BaseModel):
    learner_id: str
    language_code: Literal['en'] = 'en'
    skill_id: str
    competency_id: str
    assessment_status: Literal['not_assessed', 'observed']
    evidence_type: str
    evidence_source: str
    evidence_reference: str
    evidence_validity: str
    evaluation_method: str
    evaluation_rule_version: str | None = None
    content_version: str | None
    observed_at: datetime
    observation: str
    limitations: list[str]

    @field_validator('observed_at')
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Skill(BaseModel):
    skill_id: str
    assessment_status: Literal['not_assessed', 'observed']
    has_learning_record: bool
    evidence_levels: list[str]
    evidence: list[Evidence]
    limitations: list[str]


class LearnerModel(BaseModel):
    contract_version: Literal['1.0'] = '1.0'
    learner_id: str
    language_code: Literal['en'] = 'en'
    skills: list[Skill]
    learning_goal: dict[str, Any] | None


LIMITS = {
    'listening': ['仅反映具体练习的客观作答，不能推断整体听力水平或 IELTS 分数。'],
    'reading': ['作答、独立迁移及延迟复习只反映相应题目，不代表整体阅读水平或永久掌握。'],
    'writing': ['字数和修订行为不评价写作语义质量；写作水平未评估。'],
    'speaking': ['自查由学习者提供，并非系统语音检测；口语水平未评估。'],
}


@router.get('/learner-model', response_model=LearnerModel)
def learner_model(learner_id: str = Query(default='default_learner', min_length=1, max_length=64),
                  db: Session = Depends(get_db)) -> LearnerModel:
    sessions = db.execute(select(LearningSession, KnowledgeTopic).join(KnowledgeTopic).where(
        LearningSession.learner_id == learner_id)).all()
    by_skill: dict[str, list[LearningSession]] = {k: [] for k in LIMITS}
    for session, topic in sessions:
        domain = topic.domain_code
        skill = domain.removeprefix('ielts_') if domain in ('ielts_listening', 'ielts_writing', 'ielts_speaking') else ('reading' if domain in ('ielts_academic', 'ielts_general_training') else None)
        if skill:
            by_skill[skill].append(session)
    result = []
    for skill in ('listening', 'speaking', 'reading', 'writing'):
        records: list[Evidence] = []
        ids = [s.id for s in by_skill[skill]]
        def add(**kwargs: Any) -> None:
            records.append(Evidence(learner_id=learner_id, skill_id=skill, limitations=LIMITS[skill], **kwargs))
        if ids and skill in ('reading', 'listening'):
            attempts = db.scalars(select(Attempt).where(Attempt.session_id.in_(ids)).order_by(Attempt.submitted_at)).all()
            reviews = db.scalars(select(ReviewItem).where(ReviewItem.learner_id == learner_id, ReviewItem.attempt_id.in_([a.id for a in attempts]))).all() if attempts else []
            review_by_attempt = {r.attempt_id: r for r in reviews}
            for a in attempts:
                if skill == 'listening' and (a.item_evaluation_json or {}).get('evaluation_source') != 'rule_check':
                    continue
                valid = evidence_status(db, 'attempt', a.id) if skill == 'reading' else 'eligible'
                review = review_by_attempt.get(a.id)
                if review and evidence_status(db, 'review_item', review.id) != 'eligible':
                    valid = evidence_status(db, 'review_item', review.id)
                kind = 'practice_performance'
                if skill == 'reading' and a.attempt_role == 'transfer_check': kind = 'independent_transfer'
                if skill == 'reading' and a.attempt_role == 'review' and review and review.retention_eligible and review.retention_verified: kind = 'delayed_review'
                # A review without verified scheduling is merely a practice observation.
                version = db.get(ReadingGroupVersion, a.group_version_id) if a.group_version_id else None
                evaluated = a.evaluation_status == 'evaluated' and a.is_correct is not None
                add(competency_id=a.question.topic_id, assessment_status='observed' if evaluated and a.is_correct is True and valid == 'eligible' else 'not_assessed',
                    evidence_type=kind, evidence_source='attempt', evidence_reference=a.id, evidence_validity=valid,
                    evaluation_method='rule_check' if evaluated else 'not_evaluated', evaluation_rule_version=a.evaluation_rule_version,
                    content_version=version.content_version if version else a.question_snapshot_json.get('content_version') or str(a.question_version),
                    observed_at=a.submitted_at, observation=('正确' if a.is_correct else '错误') if evaluated else '作答尚未评价')
        if ids and skill == 'writing':
            drafts = db.scalars(select(WritingDraft).where(WritingDraft.session_id.in_(ids))).all()
            for d in drafts:
                if d.body:
                    add(competency_id='writing_expression', assessment_status='not_assessed', evidence_type='practice_activity', evidence_source='writing_draft', evidence_reference=d.session_id, evidence_validity='not_evaluated', evaluation_method='activity_record', content_version=d.task_snapshot.get('version'), observed_at=d.updated_at, observation='已保存写作草稿')
                revisions = db.scalars(select(WritingRevision).where(WritingRevision.session_id == d.session_id).order_by(WritingRevision.number)).all()
                for rev in revisions:
                    add(competency_id='writing_expression', assessment_status='not_assessed', evidence_type='practice_activity', evidence_source='writing_revision', evidence_reference=rev.id, evidence_validity='not_evaluated', evaluation_method='deterministic_text_metrics', content_version=d.task_snapshot.get('version'), observed_at=rev.submitted_at, observation=f"第 {rev.number} 次提交，{rev.feedback.get('word_count', 0)} 词" + ('，基于前次修订' if rev.source_revision_id else ''))
        if ids and skill == 'speaking':
            practices = db.scalars(select(SpeakingPractice).where(SpeakingPractice.session_id.in_(ids)).order_by(SpeakingPractice.completed_at)).all()
            for p in practices:
                add(competency_id='speaking_expression', assessment_status='not_assessed', evidence_type='practice_activity', evidence_source='speaking_practice', evidence_reference=p.recording_id, evidence_validity='not_evaluated', evaluation_method='learner_self_check', content_version=p.prompt_version, observed_at=p.completed_at, observation=f'录音练习 {p.duration_seconds:g} 秒；用户自查 {len(p.self_check)} 项')
        levels = []
        if ids: levels.append('practice_activity')
        for level in ('practice_performance', 'independent_transfer', 'delayed_review'):
            if any(e.evidence_type == level and e.assessment_status == 'observed' for e in records): levels.append(level)
        result.append(Skill(skill_id=skill, assessment_status='observed' if any(e.assessment_status == 'observed' for e in records) else 'not_assessed', has_learning_record=bool(ids), evidence_levels=levels, evidence=records, limitations=LIMITS[skill]))
    goal = db.get(ExamPreparationProfile, learner_id)
    return LearnerModel(learner_id=learner_id, skills=result, learning_goal={
        'exam_variant': goal.exam_variant, 'goal_type': goal.goal_type,
        'target_overall_band': goal.target_overall_band, 'target_skill_bands': goal.target_skill_bands,
        'target_outcome': goal.target_outcome, 'exam_date': goal.exam_date.isoformat() if goal.exam_date else None,
    } if goal else None)
