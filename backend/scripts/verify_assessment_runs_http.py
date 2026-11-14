"""Real HTTP restart acceptance against an isolated database."""
import json, os, socket, subprocess, sys, time
from pathlib import Path
from tempfile import TemporaryDirectory
import httpx
from app.persistence.migrations_runner import upgrade_database

ROOT = Path(__file__).resolve().parents[2]

def main():
    with TemporaryDirectory(prefix='assessment-run-') as temp:
        url = f"sqlite:///{(Path(temp) / 'test.sqlite3').as_posix()}"
        upgrade_database(database_url=url)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'DATABASE_URL': url, 'APP_ENV': 'testing', 'MODEL_PROVIDER': 'fake', 'MODEL_API_KEY': '', 'ALLOW_REMOTE_MODEL_CALLS': 'false'}
        process = None
        steps = []
        def start():
            p = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'], cwd=ROOT / 'backend', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(150):
                if p.poll() is not None: raise RuntimeError('Uvicorn exited')
                try:
                    if httpx.get(base + '/openapi.json', timeout=1, trust_env=False).status_code == 200: return p
                except httpx.TransportError: pass
                time.sleep(.1)
            p.terminate(); p.wait(timeout=10)
            raise RuntimeError('Uvicorn startup timeout')
        def stop(p):
            p.terminate()
            try: p.wait(timeout=10)
            except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=10)
        try:
            process = start()
            with httpx.Client(base_url=base, trust_env=False, timeout=10) as client:
                def call(step, method, path, **kwargs):
                    response = client.request(method, path, **kwargs)
                    steps.append({'step': step, 'method': method, 'path': path, 'request': kwargs, 'status': response.status_code, 'response': response.json()})
                    return response
                body = {'learner_id': 'http-assessment-test', 'assessment_version': 'initial-v1', 'idempotency_key': 'http-first'}
                response = call('create', 'POST', '/api/v1/assessment-runs', json=body)
                assert response.status_code == 200
                first = response.json()
                path = '/api/v1/assessment-runs/' + first['run_id']
                params = {'learner_id': body['learner_id']}
                assert call('get', 'GET', path, params=params).json() == first
                assert call('other_learner', 'GET', path, params={'learner_id': 'other'}).status_code == 404
                stop(process); process = None
                process = start()
                assert call('restore_after_restart', 'GET', path, params=params).json() == first
                assert call('idempotent_retry', 'POST', '/api/v1/assessment-runs', json=body).json() == first
                assert call('conflict', 'POST', '/api/v1/assessment-runs', json={**body, 'assessment_version': 'changed'}).status_code == 409
                second = call('second_run', 'POST', '/api/v1/assessment-runs', json={**body, 'idempotency_key': 'http-second'}).json()
                assert second['run_id'] != first['run_id']
                history = call('history', 'GET', '/api/v1/assessment-runs', params=params).json()
                assert {r['run_id'] for r in history} == {first['run_id'], second['run_id']}
            output = ROOT / 'docs/development/assessment-run-http-evidence.json'
            output.write_text(json.dumps({'isolated_sqlite': True, 'uvicorn_restart': True, 'steps': steps}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'HTTP acceptance passed: {output}')
        finally:
            if process is not None: stop(process)

if __name__ == '__main__': main()
