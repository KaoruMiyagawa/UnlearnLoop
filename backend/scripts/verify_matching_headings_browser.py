"""Run the Phase 5 Chrome journey on an isolated Uvicorn/SQLite fixture."""
from datetime import timedelta
import json
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import time

import httpx
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
import uvicorn

from app.api.v1.dependencies import clear_engine_cache, get_db, get_learning_service
from app.application.learning_service import LearningAppService
from app.config import Settings, get_settings
from app.main import create_app
from app.persistence.database import create_db_engine, create_session_factory
from app.persistence.migrations_runner import upgrade_database
from app.persistence.models import Attempt, DiagnosticCase, EvidenceLink, KnowledgeState, LearningSession, ReviewItem
from scripts.verify_matching_headings_transfer_review_http import ControlledClock, _seed

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get("PHASE6_OUTPUT", ROOT / "docs/development/ielts-2b1-phase5-browser-evidence"))


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def await_http(url, process=None):
    deadline = time.monotonic() + 20
    with httpx.Client(trust_env=False, timeout=1) as client:
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"Local process exited while starting {url}")
            try:
                if client.get(url).is_success:
                    return
            except httpx.TransportError:
                pass
            time.sleep(.15)
    raise TimeoutError(url)


def sqlite_evidence(factory):
    def rows(db, model, *fields):
        return [
            {field: getattr(row, field) for field in fields}
            for row in db.scalars(select(model)).all()
        ]

    with factory() as db:
        return {
            "sessions": rows(db, LearningSession, "id", "topic_id", "status", "current_group_version_id"),
            "attempts": rows(db, Attempt, "id", "session_id", "question_id", "attempt_role", "idempotency_key",
                             "group_version_id", "structured_answer_json", "item_evaluation_json", "is_correct"),
            "diagnostic_cases": rows(db, DiagnosticCase, "id", "session_id", "trigger_attempt_id", "status"),
            "evidence": rows(db, EvidenceLink, "id", "hypothesis_id", "attempt_id", "source_ref", "relation"),
            "knowledge": rows(db, KnowledgeState, "id", "topic_id", "status", "last_transfer_attempt_id"),
            "reviews": rows(db, ReviewItem, "id", "session_id", "review_session_id", "question_id",
                            "group_version_id", "trigger_attempt_id", "attempt_id", "status",
                            "retention_verified", "review_outcome", "scheduled_for"),
        }


def main():
    with TemporaryDirectory(prefix="verbatrail-phase5-") as temp:
        temporary = Path(temp)
        db_path = temporary / "phase5.sqlite3"
        clock_file = temporary / "clock-offset-days.txt"
        clock_file.write_text("0")
        base_clock = ControlledClock()
        api_port, ui_port, browser_port = [free_port() for _ in range(3)]
        api, ui, browser = [f"http://127.0.0.1:{port}" for port in (api_port, ui_port, browser_port)]
        settings = Settings(
            APP_ENV="testing", DATABASE_URL=f"sqlite:///{db_path.as_posix()}", CORS_ORIGINS=ui,
            MODEL_PROVIDER="fake", MODEL_API_KEY="", ALLOW_REMOTE_MODEL_CALLS=False,
            REVIEW_INTERVALS_DAYS=(1, 3),
        )
        engine = create_db_engine(settings)
        upgrade_database(database_url=settings.database_url, engine=engine)
        factory = create_session_factory(engine)
        _seed(factory)
        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        def service(db: Session = Depends(get_db)):
            return LearningAppService(
                db, settings=settings,
                clock=lambda: base_clock() + timedelta(days=int(clock_file.read_text())),
            )

        app.dependency_overrides[get_learning_service] = service
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
        thread = Thread(target=server.run, daemon=True)
        thread.start()
        env = {**os.environ, "VITE_API_BASE_URL": api, "SMOKE_API_URL": api, "SMOKE_UI_URL": ui,
               "SMOKE_CDP_URL": browser, "SMOKE_OUTPUT_DIR": str(OUTPUT), "PHASE5_CLOCK": str(clock_file)}
        chrome = os.environ.get("CHROME_BIN", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        processes = []
        try:
            await_http(f"{api}/openapi.json")
            for args, cwd, url in [
                (["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port",
                  str(ui_port), "--strictPort"], ROOT / "frontend", ui),
                ([chrome, "--headless=new", f"--user-data-dir={temporary / 'chrome'}",
                  f"--remote-debugging-port={browser_port}", "--disable-gpu", "about:blank"],
                 ROOT, f"{browser}/json/list"),
            ]:
                process = subprocess.Popen(args, cwd=cwd, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(process)
                await_http(url, process)
            OUTPUT.mkdir(parents=True, exist_ok=True)
            subprocess.run(["node", "scripts/verify-matching-headings-browser.mjs"], cwd=ROOT / "frontend",
                           env=env, check=True)
            snapshot = sqlite_evidence(factory)
            group_attempts = [attempt for attempt in snapshot["attempts"] if attempt["group_version_id"]]
            assignments = {(attempt["session_id"], attempt["question_id"], attempt["group_version_id"]) for attempt in group_attempts}
            assert len(assignments) == len(group_attempts), "A group assignment produced duplicate attempts"
            (OUTPUT / "sqlite-evidence.json").write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        finally:
            for process in reversed(processes):
                process.terminate()
                process.wait(timeout=10)
            server.should_exit = True
            thread.join(timeout=10)
            clear_engine_cache()
            engine.dispose()


if __name__ == "__main__":
    main()
