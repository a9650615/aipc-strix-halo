"""Integration tests for codexbar-usage + codexbar-gui cooperation.

These tests require both `codexbar_usage` and `codexbar_gui` to be importable.
When running outside the built image (e.g., in this repo's venv), the modules
may not be installed — in that case we skip gracefully instead of failing.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Generator

import pytest


# ---------------------------------------------------------------------------
# Skip helpers — integration tests need both modules installed
# ---------------------------------------------------------------------------

_codexbar_usage_available: bool | None = None


def _has_codexbar_usage() -> bool:
    global _codexbar_usage_available
    if _codexbar_usage_available is None:
        try:
            import codexbar_usage  # noqa: F401
            _codexbar_usage_available = True
        except ImportError:
            _codexbar_usage_available = False
    return _codexbar_usage_available


_codexbar_gui_available: bool | None = None


def _has_codexbar_gui() -> bool:
    global _codexbar_gui_available
    if _codexbar_gui_available is None:
        try:
            import codexbar_gui  # noqa: F401
            _codexbar_gui_available = True
        except ImportError:
            _codexbar_gui_available = False
    return _codexbar_gui_available


requires_usage = pytest.mark.skipif(
    not _has_codexbar_usage(),
    reason="codexbar_usage not installed (skip outside built image)",
)
requires_gui = pytest.mark.skipif(
    not _has_codexbar_gui(),
    reason="codexbar_gui not installed (skip outside built image)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_codexbar_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    for key in [k for k in os.environ if k.startswith("CODEXBAR_")]:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def unused_port() -> int:
    """Return a TCP port that is not currently in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Test: CLI entry point is importable
# ---------------------------------------------------------------------------

@requires_usage
def test_cli_importable():
    import codexbar_usage
    assert codexbar_usage.__version__ == "0.1.0"


@requires_usage
def test_cli_main_module():
    """python -m codexbar_usage should work."""
    result = subprocess.run(
        [sys.executable, "-m", "codexbar_usage", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "AI coding usage tracker" in result.stdout


@requires_usage
def test_cli_entry_point_exists():
    """The aipc-usage entry point should be importable."""
    from codexbar_usage.cli import cli
    assert cli is not None


# ---------------------------------------------------------------------------
# Test: Server module is importable
# ---------------------------------------------------------------------------

@requires_usage
def test_server_importable():
    import codexbar_usage.server
    assert hasattr(codexbar_usage.server, "run_server")
    assert hasattr(codexbar_usage.server, "run_server_in_thread")


# ---------------------------------------------------------------------------
# Test: serve command exists in CLI
# ---------------------------------------------------------------------------

@requires_usage
def test_serve_command_exists():
    from click.testing import CliRunner
    from codexbar_usage.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--host" in result.output


# ---------------------------------------------------------------------------
# Test: Server starts and responds to health check
# ---------------------------------------------------------------------------

@requires_usage
def test_server_health_endpoint(unused_port: int):
    """Start the server and verify /health responds with {status: ok}."""
    from codexbar_usage.server import run_server_in_thread
    import urllib.request

    thread = run_server_in_thread(port=unused_port)
    try:
        deadline = time.monotonic() + 10
        ready = False
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{unused_port}/health", timeout=2
                ) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read())
                        assert data["status"] == "ok"
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)

        assert ready, "Server did not become ready within 10s"
    finally:
        import codexbar_usage.server
        if hasattr(codexbar_usage.server, '_server'):
            codexbar_usage.server._server.shutdown()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test: Usage endpoint returns data
# ---------------------------------------------------------------------------

@requires_usage
def test_usage_endpoint_returns_list(unused_port: int):
    """The /usage endpoint should return a JSON list (possibly empty)."""
    from codexbar_usage.server import run_server_in_thread
    import urllib.request

    thread = run_server_in_thread(port=unused_port)
    try:
        deadline = time.monotonic() + 10
        ready = False
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{unused_port}/health", timeout=2
                ) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)

        assert ready, "Server did not become ready"

        with urllib.request.urlopen(
            f"http://127.0.0.1:{unused_port}/usage", timeout=5
        ) as resp:
            data = json.loads(resp.read())
            assert isinstance(data, list)
    finally:
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test: GUI server_launcher can detect the CLI
# ---------------------------------------------------------------------------

@requires_gui
def test_server_launcher_detects_cli():
    """server_launcher._find_cli() should return a valid path."""
    from codexbar_gui.server_launcher import _find_cli
    cli = _find_cli()
    assert cli is not None
    assert len(cli) > 0


@requires_gui
def test_server_launcher_check_server_fails_on_closed_port(unused_port: int):
    """check_server should return False for a port with no server."""
    from codexbar_gui.server_launcher import check_server
    assert check_server(port=unused_port) is False


# ---------------------------------------------------------------------------
# Test: GUI usage_panel can fetch data
# ---------------------------------------------------------------------------

@requires_gui
@requires_usage
def test_usage_panel_fetch_from_live_server(unused_port: int):
    """Start a server, then fetch from usage_panel.fetch_usage_data."""
    from codexbar_usage.server import run_server_in_thread
    from codexbar_gui.usage_panel import fetch_usage_data

    thread = run_server_in_thread(port=unused_port)
    try:
        deadline = time.monotonic() + 10
        ready = False
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{unused_port}/health", timeout=2
                ) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)

        assert ready, "Server did not become ready"

        data = fetch_usage_data(port=unused_port)
        assert isinstance(data, list)
    finally:
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test: Shared config file path
# ---------------------------------------------------------------------------

@requires_gui
@requires_usage
def test_shared_config_path():
    """Both CLI and GUI should reference the same config path."""
    from codexbar_usage.config import config_path
    from codexbar_gui.config_dialog import _CONFIG_FILE
    assert config_path() == _CONFIG_FILE


# ---------------------------------------------------------------------------
# Test: Server launcher start_server with wait
# ---------------------------------------------------------------------------

@requires_gui
@requires_usage
def test_server_launcher_start_server(unused_port: int):
    """start_server should launch the CLI serve command and wait for readiness."""
    from codexbar_gui.server_launcher import start_server, kill_server

    success, proc = start_server(port=unused_port, wait=True, timeout=30)
    assert success is True, "start_server should succeed"
    assert proc is not None, "Should return a process handle"
    kill_server()
