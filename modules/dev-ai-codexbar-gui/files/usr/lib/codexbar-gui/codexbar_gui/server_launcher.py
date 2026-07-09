"""Start official ``codexbar serve`` only; reject fake aipc-usage on the port."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from typing import Optional, Tuple

from codexbar_gui.upstream import find_codexbar_binary, is_official_serve

logger = logging.getLogger("codexbar_gui.server_launcher")

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
MAX_WAIT_SECONDS = 45
POLL_INTERVAL = 0.4

_server_proc: Optional[subprocess.Popen] = None


def check_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    return is_official_serve(host, port)


def wait_for_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = MAX_WAIT_SECONDS,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_server(host, port):
            logger.info("official codexbar serve ready http://%s:%s", host, port)
            return True
        time.sleep(POLL_INTERVAL)
    return False


def _find_cli() -> list[str]:
    binary = find_codexbar_binary()
    return [binary] if binary else []


def _port_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((host, port)) != 0
    except OSError:
        return False


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
    """Start official serve, or no-op if already official.

    If the port is occupied by the Python aipc-usage fake server, do **not**
    treat it as success — return False so the GUI falls back to CLI fetch.
    """
    global _server_proc

    if check_server(host, port):
        logger.info("Official codexbar serve already on :%s", port)
        return True, None

    if not _port_free(host, port):
        # Critical: do not log "Server already running" for fake/foreign listeners.
        logger.warning(
            "Port %s is busy but not official codexbar (e.g. python aipc-usage). "
            "Not using it. Free the port or ignore — GUI uses `codexbar usage` CLI. "
            "Check: ss -ltnp | grep %s",
            port,
            port,
        )
        return False, None

    cmd = _serve_cmd(port)
    if not cmd:
        logger.error(
            "Official codexbar binary not found. "
            "Install from https://github.com/steipete/CodexBar/releases"
        )
        return False, None

    logger.info("Starting: %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
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
