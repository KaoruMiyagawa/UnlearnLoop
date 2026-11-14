"""Real HTTP and Chrome acceptance using only isolated temporary services."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import httpx
import uvicorn
from app.api.v1.dependencies import clear_engine_cache, get_settings
from app.config import Settings
from app.main import create_app
from app.persistence.database import create_db_engine
from app.persistence.migrations_runner import upgrade_database
from scripts.verify_listening_browser import port, wait_http

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'docs/development/learner-model-evidence/profile'

def main():
    with TemporaryDirectory(prefix='verbatrail-model-') as tmp:
        api_port, ui_port, cdp_port = port(), port(), port()
        api, ui, cdp = (f'http://127.0.0.1:{p}' for p in (api_port, ui_port, cdp_port))
        settings = Settings(APP_ENV='testing', DATABASE_URL=f"sqlite:///{(Path(tmp) / 'model.sqlite3').as_posix()}", CORS_ORIGINS=ui, MODEL_PROVIDER='fake', MODEL_API_KEY='', ALLOW_REMOTE_MODEL_CALLS=False)
        engine = create_db_engine(settings); upgrade_database(database_url=settings.database_url, engine=engine)
        app = create_app(settings); app.dependency_overrides[get_settings] = lambda: settings
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=api_port, log_level='warning'))
        thread = Thread(target=server.run, daemon=True); thread.start()
        env = {**os.environ, 'VITE_API_BASE_URL': api, 'SMOKE_UI_URL': ui, 'SMOKE_CDP_URL': cdp, 'SMOKE_OUTPUT_DIR': str(OUTPUT)}
        chrome = os.environ.get('CHROME_BIN', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
        processes = []
        try:
            wait_http(api + '/openapi.json')
            for args, cwd, url in [(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(ui_port), '--strictPort'], ROOT / 'frontend', ui), ([chrome, '--headless=new', f"--user-data-dir={Path(tmp) / 'chrome'}", f'--remote-debugging-port={cdp_port}', '--disable-gpu', 'about:blank'], ROOT, cdp + '/json/list')]:
                p = subprocess.Popen(args, cwd=cwd, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); processes.append(p); wait_http(url, p)
            with httpx.Client(base_url=api, trust_env=False, timeout=10) as c:
                empty = c.get('/api/v1/learner-model?learner_id=default_learner'); empty.raise_for_status()
                assert all(s['assessment_status'] == 'not_assessed' for s in empty.json()['skills'])
                session = c.post('/api/v1/listening/sessions', json={'learner_id':'default_learner'}).json()
                answers = {q['id']:q['options'][0] for q in session['lesson']['questions']}
                result = c.post(f"/api/v1/listening/sessions/{session['session_id']}/submit", json={'answers':answers,'idempotency_key':f"listen-{session['session_id']}"}); result.raise_for_status()
                model = c.get('/api/v1/learner-model?learner_id=default_learner'); model.raise_for_status()
                assert len(model.json()['skills'][0]['evidence']) == 5
                assert all(not s['has_learning_record'] for s in c.get('/api/v1/learner-model?learner_id=other').json()['skills'])
                OUTPUT.mkdir(parents=True, exist_ok=True)
                (OUTPUT / 'http-response.json').write_text(json.dumps(model.json(), ensure_ascii=False, indent=2), encoding='utf-8')
            subprocess.run(['node', 'scripts/verify-learner-model-browser.mjs'], cwd=ROOT / 'frontend', env=env, check=True)
        finally:
            for p in reversed(processes):
                p.terminate()
                try: p.wait(timeout=10)
                except subprocess.TimeoutExpired: p.kill(); p.wait()
            server.should_exit=True; thread.join(timeout=10); clear_engine_cache(); engine.dispose()

if __name__ == '__main__': main()
