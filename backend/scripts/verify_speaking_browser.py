"""Verify Speaking through real Uvicorn, an isolated SQLite database and Chrome."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import httpx
from sqlalchemy import create_engine, text

from app.persistence.migrations_runner import upgrade_database
from scripts.verify_listening_browser import port, wait_http

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get("SPEAKING_BROWSER_OUTPUT", ROOT / "docs/development/speaking-v1.4-evidence"))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="verbatrail-speaking-") as temp:
        db_url = f"sqlite:///{(Path(temp) / 'speaking.sqlite3').as_posix()}"
        upgrade_database(database_url=db_url, revision="0008_writing_revisions")
        api_port, ui_port, chrome_port = port(), port(), port()
        api, ui, cdp = (f"http://127.0.0.1:{p}" for p in (api_port, ui_port, chrome_port))
        env = {
            **os.environ, "DATABASE_URL": db_url, "APP_ENV": "development",
            "API_V1_PREFIX": "/api/v1", "CORS_ORIGINS": ui, "MODEL_PROVIDER": "fake",
            "MODEL_API_KEY": "", "ALLOW_REMOTE_MODEL_CALLS": "false",
            "VITE_API_BASE_URL": api, "SMOKE_API_URL": api, "SMOKE_UI_URL": ui,
            "SMOKE_CDP_URL": cdp, "SMOKE_OUTPUT_DIR": str(OUTPUT),
        }
        chrome = os.environ.get("CHROME_BIN", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        commands = [
            ([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
              "--port", str(api_port), "--log-level", "warning"], ROOT / "backend", f"{api}/api/v1/health"),
            (["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port",
              str(ui_port), "--strictPort"], ROOT / "frontend", ui),
            ([chrome, "--headless=new", f"--user-data-dir={Path(temp) / 'chrome'}",
              f"--remote-debugging-port={chrome_port}", "--disable-gpu", "--use-fake-device-for-media-stream",
              "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required", "about:blank"],
             ROOT, f"{cdp}/json/list"),
        ]
        processes = []
        try:
            for command, cwd, url in commands:
                proc = subprocess.Popen(command, cwd=cwd, env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                processes.append(proc)
                wait_http(url, proc)
            with httpx.Client(base_url=api, trust_env=False, timeout=8) as client:
                payload = {"learner_id": "http-writer", "recording_id": "http-recording-v1",
                           "prompt_id": "hobby", "prompt_version": "speaking-part1-v1",
                           "duration_seconds": 2.5, "recorded_at": "2026-01-01T00:00:00Z",
                           "self_check": ["direct"]}
                statuses = {}
                for label, method, path, args, expected in [
                    ("prompts", "GET", "/api/v1/speaking/prompts", {}, 200),
                    ("create", "POST", "/api/v1/speaking/practices", {"json": payload}, 200),
                    ("retry", "POST", "/api/v1/speaking/practices", {"json": payload}, 200),
                    ("conflict", "POST", "/api/v1/speaking/practices", {"json": payload | {"duration_seconds": 4}}, 409),
                    ("other_learner", "GET", "/api/v1/speaking/practices?learner_id=other", {}, 200),
                    ("other_delete", "DELETE", "/api/v1/speaking/practices/http-recording-v1?learner_id=other", {}, 404),
                    ("history", "GET", "/api/v1/profile/history?learner_id=http-writer", {}, 200),
                    ("delete", "DELETE", "/api/v1/speaking/practices/http-recording-v1?learner_id=http-writer", {}, 200),
                    ("deleted_history", "GET", "/api/v1/profile/history?learner_id=http-writer", {}, 200),
                ]:
                    response = client.request(method, path, **args)
                    statuses[label] = response.status_code
                    assert response.status_code == expected, (label, response.text)
                    if label in ("other_learner", "deleted_history"):
                        assert response.json() == []
                    if label == "history":
                        assert response.json()[0]["kind"] == "speaking_practice"
                    if label == "create":
                        first = response.json()
                        assert first["evaluation_status"] == "not_assessed" and first["evidence_type"] == "practice_only"
                    if label == "retry":
                        assert response.json() == first
            engine = create_engine(db_url)
            with engine.connect() as connection:
                assert connection.scalar(text("select version_num from alembic_version")) == "0009_speaking_practice"
                assert connection.scalar(text("select count(*) from speaking_practices")) == 0
            engine.dispose()
            (OUTPUT / "http-evidence.json").write_text(json.dumps({"statuses": statuses,
                "migration": "0008 to 0009", "audio_uploaded": False}, indent=2) + "\n", encoding="utf-8")
            subprocess.run(["node", "scripts/verify-speaking-browser.mjs"], cwd=ROOT / "frontend",
                           env=env, check=True, timeout=180)
        finally:
            for proc in reversed(processes):
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            time.sleep(.1)


if __name__ == "__main__":
    main()
