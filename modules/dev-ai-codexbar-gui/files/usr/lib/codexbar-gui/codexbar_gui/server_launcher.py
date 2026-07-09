"""Start official ``codexbar serve`` (preferred) or aipc-usage fallback."""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from codexbar_gui.upstream import find_codexbar_binary

logger = logging.getLogger("codexbar_gui.server_launcher")

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
MAX_WAIT_SECONDS = 45
POLL_INTERVAL = 0.4

_server_proc: Optional[subprocess.Popen] = None


def _health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def check_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    try:
        req = urllib.request.Request(_health_url(host, port), method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok"
    except Exception:
        return False


def wait_for_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = MAX_WAIT_SECONDS,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_server(host, port):
            logger.info("Server ready http://%s:%s", host, port)
            return True
        time.sleep(POLL_INTERVAL)
    return False


def _serve_cmd(port: int) -> Optional[list[str]]:
    binary = find_codexbar_binary()
    if binary:
        return [binary, "serve", "--port", str(port)]
    # Fallback only — wrong data for real quotas
    for path in (
        Path("/usr/bin/aipc-usage"),
        Path("/usr/lib/aipc/tools/.venv/bin/aipc-usage"),
    ):
        if path.is_file():
            return [str(path), "serve", "--port", str(port)]
    which = shutil.which("aipc-usage")
    if which:
        return [which, "serve", "--port", str(port)]
    return [sys.executable, "-m", "codexbar_usage", "serve", "--port", str(port)]


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    wait: bool = True,
    timeout: float = MAX_WAIT_SECONDS,
) -> Tuple[bool, Optional[subprocess.Popen]]:
    global _server_proc

    if check_server(host, port):
        logger.info("Server already running")
        return True, None

    cmd = _serve_cmd(port)
    if not cmd:
        return False, None
    logger.info("Starting server: %s", " ".join(cmd))

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    modules_root = Path(__file__).resolve().parents[6]
    repo_usage = (
        modules_root
        / "dev-ai-codexbar-usage"
        / "files"
        / "usr"
        / "lib"
        / "aipc-codexbar-usage"
    )
    if repo_usage.is_dir() and "codexbar_usage" in " ".join(cmd):
        env["PYTHONPATH"] = f"{repo_usage}{os.pathsep}{env.get('PYTHONPATH', '')}"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        logger.error("Failed to start server: %s", exc)
        return False, None

    _server_proc = proc
    if wait:
        if not wait_for_server(host, port, timeout):
            logger.warning("Server did not become ready")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            _server_proc = None
            return False, None
    return True, proc


def kill_server() -> None:
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        logger.info("Stopping server pid=%s", _server_proc.pid)
        try:
            _server_proc.terminate()
            _server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None


def detect_server() -> bool:
    return check_server()
