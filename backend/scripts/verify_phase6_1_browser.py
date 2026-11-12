"""Run a real Chrome profile/review regression against an isolated Phase 6.1 API."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.v1.dependencies import clear_engine_cache, get_session_factory
from app.config import get_settings
from app.main import create_app
from scripts.verify_phase6_1_history_http import build_fixture

OUTPUT = Path(os.environ.get(
    "PHASE6_1_BROWSER_OUTPUT",
    ROOT / "docs" / "development" / "ielts-2b1-phase6-1-evidence" / "browser",
))


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def await_http(url: str, process: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + 25
    with httpx.Client(trust_env=False, timeout=1) as client:
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"Local process exited while starting {url}")
            try:
                if client.get(url).is_success:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.15)
    raise TimeoutError(f"Timed out waiting for {url}")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="verbatrail-phase6-1-browser-") as temporary:
        temp = Path(temporary)
        db_path = temp / "phase6-1-browser.sqlite"
        settings, (engine, factory), ids = build_fixture(db_path, learner_id="default_learner")
        api_port, ui_port, cdp_port = free_port(), free_port(), free_port()
        api, ui, cdp = (f"http://127.0.0.1:{port}" for port in (api_port, ui_port, cdp_port))
        settings.cors_origins = ui
        cli = Path(__file__).with_name("reconcile_matching_headings_evidence.py")
        subprocess.run([sys.executable, str(cli), "--database-url", settings.database_url,
            "--apply", "--confirm", "APPLY_PHASE6_1_TO_ISOLATED_SQLITE_ONLY"], check=True,
            capture_output=True, text=True)

        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_session_factory] = lambda: factory
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port,
            log_level="warning", access_log=False))
        thread = Thread(target=server.run, daemon=True)
        thread.start()

        chrome = os.environ.get("CHROME_BIN", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not Path(chrome).exists():
            raise FileNotFoundError(f"Headless Chrome executable not found: {chrome}")
        env = {**os.environ, "VITE_API_BASE_URL": api, "SMOKE_UI_URL": ui,
               "SMOKE_CDP_URL": cdp, "SMOKE_OUTPUT_DIR": str(OUTPUT)}
        processes: list[subprocess.Popen] = []
        try:
            await_http(f"{api}/api/v1/health")
            for command, cwd, url in [
                (["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port",
                  str(ui_port), "--strictPort"], ROOT / "frontend", ui),
                ([chrome, "--headless=new", f"--user-data-dir={temp / 'chrome-profile'}",
                  f"--remote-debugging-port={cdp_port}", "--disable-gpu", "about:blank"],
                 ROOT, f"{cdp}/json/list"),
            ]:
                process = subprocess.Popen(command, cwd=cwd, env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(process)
                await_http(url, process)
            subprocess.run(["node", "scripts/verify-phase6-1-browser.mjs"],
                cwd=ROOT / "frontend", env=env, check=True)
            print(f"Real browser evidence saved to {OUTPUT}")
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            server.should_exit = True
            thread.join(timeout=8)
            clear_engine_cache()
            engine.dispose()


if __name__ == "__main__":
    main()
