"""Server launcher — detect and start the aipc-usage HTTP server.

The CodexBar GUI polls the usage server (default port 8080) for usage data.
This module handles:

- Detecting whether the server is already running (HTTP health check)
- Launching ``aipc-usage serve`` as a subprocess if it is not
- Waiting for the server to be ready before returning control
- Reusing an existing server process when possible

The launcher uses the ``aipc-usage`` CLI entry point (installed by the
``dev-ai-codexbar-usage`` module), not the Python module directly, so the
behavior matches what users would invoke from the terminal.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import urllib.request
import urllib.error

logger = logging.getLogger("codexbar_gui.server_launcher")


DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
HEALTH_URL_TEMPLATE = "http://{host}:{port}/health"
MAX_WAIT_SECONDS = 30
POLL_INTERVAL = 0.5

# Module-level reference to prevent subprocess GC by Python's garbage collector.
# The server should outlive the GUI process so keep this reference alive.
_server_proc: Optional[subprocess.Popen] = None


def _find_cli() -> list[str]:
    """Return the command to invoke the ``aipc-usage`` CLI as a list.

    Search order:
    1. ``/usr/bin/aipc-usage`` (installed by the module)
    2. ``python -m codexbar_usage`` as fallback
    """
    direct = Path("/usr/bin/aipc-usage")
    if direct.exists():
        return [str(direct)]

    # Fallback: invoke via the Python module directly.
    # This works when running from the development tree or inside the aipc venv.
    return [sys.executable, "-m", "codexbar_usage"]


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def check_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Return True if the usage server responds to a health check."""
    url = HEALTH_URL_TEMPLATE.format(host=host, port=port)
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                return data.get("status") == "ok"
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        pass
    logger.debug("Server health check failed at %s", url)
    return False


def wait_for_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = MAX_WAIT_SECONDS,
) -> bool:
    """Block until the server is reachable or timeout expires.

    Returns True if the server responded to a health check before timeout.
    """
    # Always use a blocking poll — this runs from a worker / startup path,
    # never from inside a Qt or asyncio event loop.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_server(host, port):
            logger.info("Server ready at http://%s:%s", host, port)
            return True
        time.sleep(POLL_INTERVAL)
    return False


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    wait: bool = True,
    timeout: float = MAX_WAIT_SECONDS,
) -> Tuple[bool, Optional[subprocess.Popen]]:
    """Launch the usage server if it is not already running.

    Returns a tuple of (success, process_handle).
    ``success`` is True if the server is reachable after launch.
    ``process_handle`` is the Popen object (or None if reusing an existing server).
    """
    global _server_proc

    if check_server(host, port):
        logger.info("Server already running at http://%s:%s", host, port)
        return True, None

    cli = _find_cli()
    cmd = cli + ["serve", "--port", str(port)]
    logger.info("Starting server: %s", " ".join(cmd))

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError:
        logger.error("Server binary not found: %s", cli)
        return False, None
    except OSError as e:
        logger.error("Failed to start server: %s", e)
        return False, None

    _server_proc = proc

    if wait:
        ok = wait_for_server(host, port, timeout)
        if not ok:
            logger.warning("Server failed to start within %ds, terminating", timeout)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            _server_proc = None
            return False, None
        logger.info("Server started successfully on port %d", port)
        return True, proc

    return True, proc


def kill_server() -> None:
    """Terminate the server process if we launched it."""
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        logger.info("Terminating server process (pid=%d)", _server_proc.pid)
        try:
            _server_proc.terminate()
            _server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None


def detect_server() -> bool:
    """Convenience wrapper: returns True if server is reachable on default port."""
    return check_server()
