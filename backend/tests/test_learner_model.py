from datetime import datetime, timezone
from sqlalchemy import select
from app.persistence.models import Attempt, EvidenceValidityEvent, KnowledgeTopic, LearningSession, Question


def skill(body, name):
    return next(s for s in body['skills'] if s['skill_id'] == name)


def test_empty_and_learner_boundary(client, migrated_engine):
    empty = client.get('/api/v1/learner-model', params={'learner_id': 'new'}).json()
    assert [s['skill_id'] for s in empty['skills']] == ['listening', 'speaking', 'reading', 'writing']
    assert all(s['assessment_status'] == 'not_assessed' and not s['has_learning_record'] for s in empty['skills'])
    assert client.get('/api/v1/learner-model?learner_id=').status_code == 422
    assert client.get('/api/v1/learner-model', params={'learner_id': 'x' * 65}).status_code == 422


def test_listening_writing_speaking_and_goal(client, migrated_engine):
    learner = 'projection-user'
    session = client.post('/api/v1/listening/sessions', json={'learner_id': learner}).json()
    answers = {q['id']: q['options'][0] for q in session['lesson']['questions']}
    assert client.post(f"/api/v1/listening/sessions/{session['session_id']}/submit", json={'answers': answers, 'idempotency_key': f"listen-{session['session_id']}"}).status_code == 200
    writing = client.post('/api/v1/writing/sessions', json={'learner_id': learner}).json()
    sid = writing['session_id']
    assert client.put(f'/api/v1/writing/sessions/{sid}/draft', params={'learner_id': learner}, json={'body': 'Two words', 'version': 0}).status_code == 200
    assert client.post(f'/api/v1/writing/sessions/{sid}/revisions', params={'learner_id': learner}, json={'body': 'Two words', 'version': 1, 'idempotency_key': 'proj-write-one'}).status_code == 200
    assert client.post(f'/api/v1/writing/sessions/{sid}/revisions', params={'learner_id': learner}, json={'body': 'Three simple words', 'version': 2, 'idempotency_key': 'proj-write-two'}).status_code == 200
    prompt = client.get('/api/v1/speaking/prompts').json()[0]
    assert client.post('/api/v1/speaking/practices', json={'learner_id': learner, 'recording_id': 'projection-recording', 'prompt_id': prompt['id'], 'prompt_version': prompt['version'], 'duration_seconds': 5, 'recorded_at': datetime.now(timezone.utc).isoformat(), 'self_check': ['direct']}).status_code == 200
    assert client.put('/api/v1/profile/exam-preparation', params={'learner_id': learner}, json={'exam_variant': 'academic', 'target_overall_band': 8.0}).status_code == 200
    body = client.get('/api/v1/learner-model', params={'learner_id': learner}).json()
    listen = skill(body, 'listening')
    assert len(listen['evidence']) == 5 and listen['assessment_status'] == 'observed'
    assert all(e['evaluation_method'] == 'rule_check' and e['evaluation_rule_version'] == 'listening-exact-choice-v1' for e in listen['evidence'])
    assert all(e['assessment_status'] == ('observed' if e['observation'] == '正确' else 'not_assessed') for e in listen['evidence'])
    assert skill(body, 'writing')['assessment_status'] == 'not_assessed'
    assert len([e for e in skill(body, 'writing')['evidence'] if e['evidence_source'] == 'writing_revision']) == 2
    assert skill(body, 'speaking')['assessment_status'] == 'not_assessed'
    assert skill(body, 'speaking')['evidence'][0]['evaluation_method'] == 'learner_self_check'
    assert body['learning_goal']['target_overall_band'] == 8.0
    assert skill(body, 'reading')['assessment_status'] == 'not_assessed'
    other = client.get('/api/v1/learner-model', params={'learner_id': 'other'}).json()
    assert all(not s['has_learning_record'] for s in other['skills']) and other['learning_goal'] is None


def test_reading_validity_separates_evidence(client, session_factory):
    with session_factory() as db:
        topic = KnowledgeTopic(id='projection-reading', slug='projection-reading', domain_code='ielts_academic', title='Reading', summary='Test', difficulty_level=1)
        db.add(topic); db.flush()
        q = Question(id='projection-question', topic_id=topic.id, question_type='short_text', prompt_text='Question', standard_answer='yes', answer_explanation='Test')
        db.add(q); db.flush()
        s = LearningSession(id='projection-session', learner_id='reader-projection', topic_id=topic.id)
        db.add(s); db.flush()
        for name in ('good', 'bad', 'review'):
            db.add(Attempt(id='projection-' + name, session_id=s.id, question_id=q.id, attempt_role='transfer_check', submitted_answer='yes', is_correct=True, evaluation_status='evaluated'))
        db.flush()
        for name, status in [('bad', 'invalidated'), ('review', 'review_required')]:
            db.add(EvidenceValidityEvent(target_type='attempt', target_id='projection-' + name, status=status, reason='audit', source='test', idempotency_key='validity-' + name))
        db.commit()
    reading = skill(client.get('/api/v1/learner-model?learner_id=reader-projection').json(), 'reading')
    evidence = {e['evidence_reference']: e for e in reading['evidence']}
    assert evidence['projection-good']['assessment_status'] == 'observed'
    assert evidence['projection-bad']['evidence_validity'] == 'invalidated'
    assert evidence['projection-review']['assessment_status'] == 'not_assessed'
    assert 'independent_transfer' in reading['evidence_levels']
