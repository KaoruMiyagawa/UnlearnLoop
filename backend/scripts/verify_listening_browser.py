"""Run the real Listening journey against temporary SQLite, Uvicorn, Vite and headless Chrome."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
from sqlalchemy import select

from app.api.v1.dependencies import clear_engine_cache, get_settings
from app.config import Settings
from app.main import create_app
from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database
from app.persistence.models import Attempt, LearningSession

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "development" / "listening-v1.2-browser-evidence"


def port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def wait_http(url, process=None):
    deadline = time.monotonic() + 30
    with httpx.Client(trust_env=False, timeout=1) as client:
        while time.monotonic() < deadline:
            if process and process.poll() is not None:
                raise RuntimeError(f"Process exited during startup: {url}")
            try:
                if client.get(url).is_success:
                    return
            except httpx.TransportError:
                pass
            time.sleep(.2)
    raise TimeoutError(url)


def main():
    with TemporaryDirectory(prefix="verbatrail-listening-v12-") as temp:
        temporary = Path(temp)
        api_port, ui_port, chrome_port = port(), port(), port()
        api, ui, cdp = (f"http://127.0.0.1:{p}" for p in (api_port, ui_port, chrome_port))
        settings = Settings(APP_ENV="testing", DATABASE_URL=f"sqlite:///{(temporary / 'isolated.sqlite3').as_posix()}",
                            CORS_ORIGINS=ui, MODEL_PROVIDER="fake", MODEL_API_KEY="", ALLOW_REMOTE_MODEL_CALLS=False)
        engine = create_db_engine(settings)
        upgrade_database(database_url=settings.database_url, engine=engine)
        factory = create_session_factory(engine)
        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
        thread = Thread(target=server.run, daemon=True)
        thread.start()
        env = {**os.environ, "VITE_API_BASE_URL": api, "SMOKE_UI_URL": ui, "SMOKE_CDP_URL": cdp,
               "SMOKE_OUTPUT_DIR": str(OUTPUT), "CHROME_BIN": os.environ.get("CHROME_BIN", r"C:\Program Files\Google\Chrome\Application\chrome.exe")}
        processes = []
        try:
            wait_http(f"{api}/openapi.json")
            for args, cwd, url in [
                (["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"], ROOT / "frontend", ui),
                ([env["CHROME_BIN"], "--headless=new", f"--user-data-dir={temporary / 'chrome'}", f"--remote-debugging-port={chrome_port}", "--disable-gpu", "--autoplay-policy=no-user-gesture-required", "about:blank"], ROOT, f"{cdp}/json/list"),
            ]:
                process = subprocess.Popen(args, cwd=cwd, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(process)
                wait_http(url, process)

            # Independent live HTTP transaction and persisted-history evidence.
            with httpx.Client(trust_env=False, timeout=8) as client:
                lesson = client.get(f"{api}/api/v1/listening/lesson")
                started = client.post(f"{api}/api/v1/listening/sessions", json={"learner_id": "http-acceptance"})
                assert lesson.status_code == 200 and started.status_code == 201
                session = started.json()
                answers = {q["id"]: q["options"][0] for q in session["lesson"]["questions"]}
                submitted = client.post(f"{api}/api/v1/listening/sessions/{session['session_id']}/submit",
                                        json={"answers": answers, "idempotency_key": f"listen-{session['session_id']}"})
                replay = client.post(f"{api}/api/v1/listening/sessions/{session['session_id']}/submit",
                                     json={"answers": answers, "idempotency_key": f"listen-{session['session_id']}"})
                assert submitted.status_code == 200 and replay.status_code == 200
                http_evidence = {"lesson_status": lesson.status_code, "start_status": started.status_code,
                                 "submit_status": submitted.status_code, "retry_status": replay.status_code,
                                 "content_version": lesson.json()["content_version"],
                                 "evaluation_rule_version": lesson.json()["evaluation_rule_version"],
                                 "evaluation_source": lesson.json()["evaluation_source"],
                                 "score": submitted.json()["score"], "session_id": session["session_id"],
                                 "assessment_note": submitted.json()["assessment_note"],
                                 "history_status": client.get(f"{api}/api/v1/listening/history?learner_id=http-acceptance").status_code}
                assert http_evidence["history_status"] == 200
            OUTPUT.mkdir(parents=True, exist_ok=True)
            (OUTPUT / "http-evidence.json").write_text(json.dumps(http_evidence, indent=2), encoding="utf-8")

            subprocess.run(["node", "scripts/verify-listening-browser.mjs"], cwd=ROOT / "frontend", env=env, check=True)
            with factory() as db:
                saved = db.get(LearningSession, session["session_id"])
                attempts = db.scalars(select(Attempt).where(Attempt.session_id == session["session_id"])).all()
                assert saved and saved.status == "completed" and len(attempts) == 5
                assert all(a.question_snapshot_json["content_version"] == "listening-study-group-v1" for a in attempts)
                assert all(a.question_snapshot_json["rule_version"] == "listening-exact-choice-v1" for a in attempts)
                assert all(a.item_evaluation_json["evaluation_source"] == "rule_check" for a in attempts)
                assert not any(a.question_snapshot_json.get("transfer_verified") or a.question_snapshot_json.get("retention_verified") for a in attempts)
                evidence = {"http": http_evidence, "persisted_attempt_count": len(attempts),
                            "attempt_content_versions": sorted({a.question_snapshot_json["content_version"] for a in attempts}),
                            "attempt_rule_versions": sorted({a.question_snapshot_json["rule_version"] for a in attempts}),
                            "evaluation_sources": sorted({a.item_evaluation_json["evaluation_source"] for a in attempts}),
                            "transfer_or_retention_verified": False,
                            "isolated_database": "temporary SQLite database (deleted after the run)",
                            "production_database_touched": False}
            (OUTPUT / "persistence-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(json.dumps(evidence, indent=2))
        finally:
            for proc in reversed(processes):
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            server.should_exit = True
            thread.join(timeout=10)
            clear_engine_cache()
            engine.dispose()


if __name__ == "__main__":
    main()
