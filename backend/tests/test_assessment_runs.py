from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.persistence.database import create_db_engine
from app.persistence.migrations_runner import upgrade_database

BASE = '/api/v1/assessment-runs'


def test_migrate_from_0009(test_settings):
    engine = create_db_engine(test_settings)
    try:
        upgrade_database(database_url=test_settings.database_url, engine=engine, revision='0009_speaking_practice')
        assert 'assessment_runs' not in inspect(engine).get_table_names()
        upgrade_database(database_url=test_settings.database_url, engine=engine)
        assert {'assessment_runs', 'assessment_tasks'} <= set(inspect(engine).get_table_names())
        with engine.connect() as conn:
            assert conn.scalar(text('select version_num from alembic_version')) == '0010_assessment_runs'
    finally:
        engine.dispose()


def test_creation_restore_history_and_scope(client, migrated_engine):
    body = {'learner_id': 'alice', 'assessment_version': 'initial-v1', 'idempotency_key': 'first'}
    assert client.get(BASE, params={'learner_id': 'alice'}).json() == []
    first = client.post(BASE, json=body)
    assert first.status_code == 200, first.text
    run = first.json()
    assert run['status'] == 'in_progress' and run['completed_at'] is None
    assert [t['skill_id'] for t in run['tasks']] == ['listening', 'speaking', 'reading', 'writing']
    assert all(t['status'] == 'not_started' and t['evidence_reference'] is None for t in run['tasks'])
    assert client.get(f"{BASE}/{run['run_id']}", params={'learner_id': 'alice'}).json() == run
    assert client.post(BASE, json=body).json() == run
    assert client.post(BASE, json=body | {'assessment_version': 'another'}).status_code == 409
    assert client.get(f"{BASE}/{run['run_id']}", params={'learner_id': 'bob'}).status_code == 404
    assert client.get(BASE, params={'learner_id': 'bob'}).json() == []
    second = client.post(BASE, json=body | {'idempotency_key': 'second'}).json()
    assert second['run_id'] != run['run_id']
    assert {r['run_id'] for r in client.get(BASE, params={'learner_id': 'alice'}).json()} == {run['run_id'], second['run_id']}
    assert client.post(BASE, json=body | {'status': 'completed'}).status_code == 422
    assert client.post(BASE, json=body | {'learner_id': ' '}).status_code == 422
    assert client.patch(f"{BASE}/{run['run_id']}", json={'status': 'completed'}).status_code == 405
    with migrated_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(text("update assessment_tasks set status='completed' where run_id=:id"), {'id': run['run_id']})
        with pytest.raises(IntegrityError):
            conn.execute(text("update assessment_tasks set status='invented' where run_id=:id"), {'id': run['run_id']})


def test_concurrent_idempotency(client, migrated_engine):
    body = {'learner_id': 'concurrent', 'idempotency_key': 'same-key'}
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post(BASE, json=body), range(8)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()['run_id'] for r in responses}) == 1
    assert len(client.get(BASE, params={'learner_id': 'concurrent'}).json()) == 1
