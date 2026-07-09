"""Start official ``codexbar serve`` only.

This GUI does **not** use the Python aipc-usage port for core logic.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

from codexbar_gui.upstream import find_codexbar_binary

logger = logging.getLogger("codexbar_gui.server_launcher")

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
MAX_WAIT_SECONDS = 45
POLL_INTERVAL = 0.4

_server_proc: Optional[subprocess.Popen] = None


def check_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    try:
        req = urllib.request.Request(f"http://{host}:{port}/health", method="GET")
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
            logger.info("codexbar serve ready http://%s:%s", host, port)
            return True
        time.sleep(POLL_INTERVAL)
    return False


def _find_cli() -> list[str]:
    """Return [codexbar_binary] for tests / diagnostics."""
    binary = find_codexbar_binary()
    if not binary:
        return []
    return [binary]


def _serve_cmd(port: int) -> Optional[list[str]]:
    binary = find_codexbar_binary()
    if not binary:
        return None
    return [binary, "serve", "--port", str(port)]


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    wait: bool = True,
    timeout: float = MAX_WAIT_SECONDS,
) -> Tuple[bool, Optional[subprocess.Popen]]:
    """Start official ``codexbar serve`` if nothing is listening."""
    global _server_proc

    if check_server(host, port):
        logger.info("Server already running")
        return True, None

    cmd = _serve_cmd(port)
    if not cmd:
        logger.error(
            "Official codexbar binary not found. Install the Linux CLI from "
            "https://github.com/steipete/CodexBar/releases — GUI does not reimplement core."
        )
        return False, None

    logger.info("Starting: %s", " ".join(cmd))
    env = os.environ.copy()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        logger.error("Failed to start codexbar serve: %s", exc)
        return False, None

    _server_proc = proc
    if wait and not wait_for_server(host, port, timeout):
        logger.warning("codexbar serve did not become ready")
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
        logger.info("Stopping codexbar serve pid=%s", _server_proc.pid)
        try:
            _server_proc.terminate()
            _server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None


def detect_server() -> bool:
    return check_server()
