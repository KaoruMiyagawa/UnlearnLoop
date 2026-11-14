import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import httpx
import uvicorn
from tests.test_tfng_api import tfng_client
from tests.test_ielts_pivot import ielts_client
import app.application.learning_service as learning


@pytest.fixture
def live_tfng_client(tfng_client):
    """Exercise real localhost HTTP while preserving the isolated fixture database."""
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(tfng_client.app, lifespan='off', log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    for _ in range(500):
        if server.started:
            break
        time.sleep(.01)
    assert server.started
    with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10, trust_env=False) as client:
        yield client
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
    assert not thread.is_alive()


@pytest.mark.parametrize('variant,tag,target,loc,logic', [
    ('academic','acad','logic','B','FALSE'),
    ('academic','acad','location','A','NOT GIVEN'),
    ('general_training','gt','logic','B','FALSE'),
    ('general_training','gt','location','A','NOT GIVEN'),
])
@pytest.mark.parametrize('outcome', ['pass', 'transfer_fail', 'review_fail', 'unavailable', 'version_mismatch'])
def test_tfng_transfer_review_http(live_tfng_client, session_factory, monkeypatch, variant, tag, target, loc, logic, outcome):
    clock = [datetime(2026, 11, 11, tzinfo=timezone.utc)]
    monkeypatch.setattr(learning, 'utc_now', lambda: clock[0])
    c = live_tfng_client
    trace = []
    def call(method, url, body=None, expected=(200, 201)):
        response = getattr(c, method)(url, json=body) if body is not None else getattr(c, method)(url)
        assert response.status_code in expected, response.text
        result = response.json()
        trace.append({'method': method, 'url': url, 'request': body, 'status': response.status_code, 'response': result})
        return result
    call('put', '/api/v1/profile/exam-preparation', {'exam_variant': variant})
    prefix = 'ielts-tfng-' + tag
    session = call('post', '/api/v1/sessions', {'topic_id': prefix+'-reading-english', 'exam_variant': variant})
    sid = session['id']
    initial = call('post', f'/api/v1/sessions/{sid}/attempts', {'question_id':prefix+'-initial','submitted_answer':'FALSE','idempotency_key':sid+'-initial'})
    case = initial['diagnostic_case_id']
    call('get', f'/api/v1/diagnoses/{case}/hypotheses')
    for i, (suffix, answer) in enumerate([('locate',loc),('logic',logic)]):
        step = call('post', f'/api/v1/diagnoses/{case}/step', {'idempotency_key':sid+'-step'+str(i)})
        assert step['next_question']['id'] == prefix+'-'+suffix
        call('post', f'/api/v1/sessions/{sid}/attempts', {'question_id':prefix+'-'+suffix,'submitted_answer':answer,'idempotency_key':sid+'-'+suffix})
    call('get', f'/api/v1/diagnoses/{case}/hypotheses')
    call('get', f'/api/v1/diagnoses/{case}/evidence')
    step = call('post', f'/api/v1/diagnoses/{case}/step', {'idempotency_key':sid+'-practice-step'})
    assert step['next_question']['id'] == prefix+'-practice-'+target
    states = {h['error_code']: h['status'] for h in call('get', f'/api/v1/diagnoses/{case}/hypotheses')}
    assert states['true_false_not_given'] == ('supported' if target == 'logic' else 'lowered')
    assert states['passage_location'] == ('supported' if target == 'location' else 'lowered')
    call('get', f'/api/v1/diagnoses/{case}/evidence')
    if outcome in ('unavailable', 'version_mismatch'):
        from app.persistence.models import Question
        with session_factory() as db:
            q = db.get(Question, prefix+'-transfer-'+target)
            if outcome == 'unavailable':
                db.delete(q)
            else:
                q.evaluation_rubric = {**q.evaluation_rubric, 'diagnostic_version': 'incompatible-v2'}
            db.commit()
    practice = call('post', f'/api/v1/sessions/{sid}/attempts', {'question_id':prefix+'-practice-'+target,'submitted_answer':'NOT GIVEN' if target=='logic' else 'B','idempotency_key':sid+'-practice'})
    if outcome in ('unavailable', 'version_mismatch'):
        assert practice['next_action'] == 'transfer_unavailable'
        assert practice['next_question'] is None
        assert practice['knowledge_state_status'] == 'insufficient_evidence'
        return
    assert practice['next_question'] is not None, practice
    assert practice['next_question']['id'] == prefix+'-transfer-'+target
    assert 'standard_answer' not in practice['next_question'] and 'evaluation_rubric' not in practice['next_question']
    assert practice['next_question']['material_id'] != session['current_question']['material_id']
    body={'question_id':prefix+'-transfer-'+target,'submitted_answer':('FALSE' if target=='logic' else 'A') if outcome=='transfer_fail' else ('NOT GIVEN' if target=='logic' else 'B'),'idempotency_key':sid+'-transfer'}
    transfer=call('post', f'/api/v1/sessions/{sid}/attempts', body)
    assert call('post', f'/api/v1/sessions/{sid}/attempts', body)['attempt_id']==transfer['attempt_id']
    call('get', f'/api/v1/sessions/{sid}')
    assert transfer['knowledge_state_status'] == ('needs_practice' if outcome=='transfer_fail' else 'transfer_verified')
    reviews=call('get','/api/v1/reviews')
    review=next(r for r in reviews if r['topic_id']==prefix+'-reading-english')
    if outcome != 'transfer_fail':
        assert review['retention_eligible'] and not review['retention_verified']
        call('post', f"/api/v1/reviews/{review['id']}/start", expected=(400,))
        call('post', f"/api/v1/reviews/{review['id']}/complete", {}, expected=(400,))
        clock[0] += timedelta(days=2)
        started=call('post', f"/api/v1/reviews/{review['id']}/start")
        assert started['question_id']==prefix+'-review-'+target
        assert 'standard_answer' not in started['current_question'] and 'evaluation_rubric' not in started['current_question']
        answer=('FALSE' if target=='logic' else 'A') if outcome=='review_fail' else ('NOT GIVEN' if target=='logic' else 'B')
        review_body={'question_id':started['question_id'],'submitted_answer':answer,'idempotency_key':sid+'-review'}
        result=call('post', f"/api/v1/sessions/{started['review_session_id']}/attempts", review_body)
        replay=call('post', f"/api/v1/sessions/{started['review_session_id']}/attempts", review_body)
        assert replay['attempt_id'] == result['attempt_id']
        review=call('get', f"/api/v1/reviews/{review['id']}")
        assert review['retention_verified'] == (outcome=='pass')
        model = call('get', '/api/v1/learner-model')
        reading = next(item for item in model['skills'] if item['skill_id'] == 'reading')
        assert 'independent_transfer' in reading['evidence_levels']
        assert ('delayed_review' in reading['evidence_levels']) == (outcome == 'pass')
        assert result['next_action'] == ('delayed_retention_verified' if outcome=='pass' else 'review_failed_needs_diagnosis')
        if outcome == 'review_fail':
            assert result['knowledge_state_status'] == 'needs_practice'
    else:
        assert not review['retention_eligible']
        clock[0] += timedelta(days=2)
        started = call('post', f"/api/v1/reviews/{review['id']}/start")
        assert started['question_id'] == prefix+'-review-'+target
        result = call('post', f"/api/v1/sessions/{started['review_session_id']}/attempts", {
            'question_id': started['question_id'], 'submitted_answer': 'NOT GIVEN' if target == 'logic' else 'B',
            'idempotency_key': sid+'-remediation-review'})
        assert result['next_action'] == 'review_passed_without_retention'
        review = call('get', f"/api/v1/reviews/{review['id']}")
        assert not review['retention_verified']
    call('get', '/api/v1/profile/knowledge-states')
    if os.getenv('TFNG_2A2_TRACE_DIR'):
        from sqlalchemy import select
        from app.persistence.models import Attempt, KnowledgeState, ReviewItem
        with session_factory() as db:
            state = db.scalar(select(KnowledgeState).where(KnowledgeState.topic_id == prefix+'-reading-english'))
            items = db.scalars(select(ReviewItem).where(ReviewItem.topic_id == prefix+'-reading-english')).all()
            attempts = db.scalars(select(Attempt).where(Attempt.session_id == sid)).all()
            trace.append({'database_evidence': {'knowledge_status': state.status,
                'last_transfer_attempt_id': state.last_transfer_attempt_id,
                'attempts': [{'id': a.id, 'question_id': a.question_id, 'version': a.question_version, 'correct': a.is_correct} for a in attempts],
                'reviews': [{'id': item.id, 'hypothesis_id': item.hypothesis_id, 'status': item.status,
                             'attempt_id': item.attempt_id, 'retention_verified': item.retention_verified,
                             'outcome': item.review_outcome} for item in items]}})
        out=Path(os.environ['TFNG_2A2_TRACE_DIR']); out.mkdir(parents=True,exist_ok=True)
        (out/f'{tag}-{target}-{outcome}.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
