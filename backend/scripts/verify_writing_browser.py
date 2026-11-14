"""Run the Writing acceptance against Uvicorn and an isolated SQLite file."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import httpx
from sqlalchemy import create_engine, text

from app.persistence.migrations_runner import upgrade_database
from scripts.verify_listening_browser import port, wait_http

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get("WRITING_BROWSER_OUTPUT", ROOT / "docs/development/writing-v1.3-evidence"))


def request(client, evidence, label, method, path, status=200, **kwargs):
    response = client.request(method, path, **kwargs)
    evidence[label] = response.status_code
    assert response.status_code == status, (label, response.text)
    return response.json()


def verify_http(api, db_url):
    evidence = {}
    base = "/api/v1/writing/sessions"
    with httpx.Client(base_url=api, trust_env=False, timeout=10) as client:
        def call(label, method, path, status=200, **kwargs):
            return request(client, evidence, label, method, path, status, **kwargs)

        opened = call("open", "POST", base, json={"learner_id": "writing-http"})
        sid = opened["session_id"]
        params = {"learner_id": "writing-http"}
        path = f"{base}/{sid}"
        essay = "Community gardens bring neighbours together.\n\nSports spaces also support exercise."
        draft = call("save", "PUT", f"{path}/draft", params=params, json={"body": essay, "version": 0})
        restored = call("reopen", "POST", base, json=params)
        assert restored["draft"] == draft
        call("stale_save", "PUT", f"{path}/draft", 409, params=params, json={"body": "stale", "version": 0})
        payload = {"body": essay, "version": 1, "idempotency_key": "writing-http-first"}
        first = call("submit", "POST", f"{path}/revisions", params=params, json=payload)
        assert first == call("retry", "POST", f"{path}/revisions", params=params, json=payload)
        payload = {"body": essay + " Both deserve attention.", "version": 2, "idempotency_key": "writing-http-second"}
        second = call("revise", "POST", f"{path}/revisions", params=params, json=payload)
        assert second["source_revision_id"] == first["id"]
        assert second["feedback"]["word_count_change"] == 3
        revision_url = f"{path}/revisions/{first['id']}"
        assert call("old_revision", "GET", revision_url, params=params)["body"] == essay
        call("other_learner", "GET", revision_url, 404, params={"learner_id": "another"})
        history = call("shared_history", "GET", "/api/v1/profile/history", params=params)
        assert [event["kind"] for event in history] == ["writing_submission"] * 2
        assert essay not in json.dumps(history)

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM attempts WHERE session_id = :id"), {"id": sid}) == 0
            versions = conn.execute(text(
                "SELECT number, body FROM writing_revisions WHERE session_id = :id ORDER BY number"
            ), {"id": sid}).all()
            assert versions == [(1, essay), (2, payload["body"])]
            head = conn.scalar(text("SELECT version_num FROM alembic_version"))
            assert head == "0009_speaking_practice"
    finally:
        engine.dispose()
    return {"http_statuses": evidence, "database_head": head, "revision_count": len(versions),
            "related_choice_attempts": 0, "old_text_preserved": True, "rule_version": first["feedback"]["rule_version"]}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="verbatrail-writing-") as temp:
        database = f"sqlite:///{(Path(temp) / 'writing.sqlite3').as_posix()}"
        upgrade_database(database_url=database, revision="0007_evidence_validity_events")
        api_port, ui_port, cdp_port = port(), port(), port()
        api, ui, cdp = (f"http://127.0.0.1:{number}" for number in (api_port, ui_port, cdp_port))
        env = {
            **os.environ, "DATABASE_URL": database, "APP_ENV": "development",
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
              f"--remote-debugging-port={cdp_port}", "--disable-gpu", "about:blank"], ROOT, f"{cdp}/json/list"),
        ]
        processes = []
        try:
            for command, cwd, url in commands:
                proc = subprocess.Popen(command, cwd=cwd, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                processes.append(proc)
                wait_http(url, proc)
            evidence = verify_http(api, database)
            (OUTPUT / "http-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            subprocess.run(["node", "scripts/verify-writing-browser.mjs"], cwd=ROOT / "frontend", env=env, check=True)
        finally:
            for proc in reversed(processes):
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    main()
