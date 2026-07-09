"""Integration tests for codexbar-usage + codexbar-gui cooperation.

These tests verify that:
1. The CLI module can be imported and run
2. The server can start and respond to requests
3. The GUI's server_launcher can start the CLI serve command
4. Data can be fetched from the server via HTTP
5. Both modules share the same config path
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Generator

import pytest


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
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def cli_module_dir() -> Path:
    return Path(__file__).parent.parent / "modules" / "dev-ai-codexbar-usage" / "files" / "usr" / "lib" / "aipc-codexbar-usage"


@pytest.fixture
def gui_module_dir() -> Path:
    return Path(__file__).parent.parent / "modules" / "dev-ai-codexbar-gui" / "files" / "usr" / "lib" / "codexbar-gui"


# ---------------------------------------------------------------------------
# Test: CLI module can be imported
# ---------------------------------------------------------------------------

def test_cli_module_importable(cli_module_dir: Path):
    sys.path.insert(0, str(cli_module_dir))
    import codexbar_usage
    assert codexbar_usage.__version__ == "0.1.0"


def test_cli_main_module(cli_module_dir: Path):
    """python -m codexbar_usage should work."""
    result = subprocess.run(
        [sys.executable, "-m", "codexbar_usage", "--help"],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "PYTHONPATH": str(cli_module_dir)},
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "serve" in result.stdout


# ---------------------------------------------------------------------------
# Test: Server module exists and is importable
# ---------------------------------------------------------------------------

def test_server_module_importable(cli_module_dir: Path):
    sys.path.insert(0, str(cli_module_dir))
    import codexbar_usage.server
    assert hasattr(codexbar_usage.server, "run_server")
    assert hasattr(codexbar_usage.server, "run_server_in_thread")


# ---------------------------------------------------------------------------
# Test: serve command exists in CLI
# ---------------------------------------------------------------------------

def test_serve_command_exists(cli_module_dir: Path):
    sys.path.insert(0, str(cli_module_dir))
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
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test: Usage endpoint returns data
# ---------------------------------------------------------------------------

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

def test_server_launcher_detects_cli(gui_module_dir: Path):
    """server_launcher._find_cli() should return a valid path."""
    sys.path.insert(0, str(gui_module_dir))
    from codexbar_gui.server_launcher import _find_cli
    cli = _find_cli()
    assert cli is not None
    assert len(cli) > 0


def test_server_launcher_check_server_fails_on_closed_port(unused_port: int):
    """check_server should return False for a port with no server."""
    sys.path.insert(0, str(gui_module_dir))
    from codexbar_gui.server_launcher import check_server
    assert check_server(port=unused_port) is False


# ---------------------------------------------------------------------------
# Test: GUI server_launcher can start CLI server
# ---------------------------------------------------------------------------

def test_server_launcher_start_server(unused_port: int, gui_module_dir: Path):
    """start_server should launch the CLI serve command and wait for readiness."""
    sys.path.insert(0, str(gui_module_dir))
    from codexbar_gui.server_launcher import start_server, kill_server

    success, proc = start_server(port=unused_port, wait=True, timeout=30)
    assert success is True, "start_server should succeed"
    assert proc is not None, "Should return a process handle"
    kill_server()


def test_server_launcher_fetch_data(unused_port: int, gui_module_dir: Path):
    """After starting via server_launcher, data should be fetchable via HTTP."""
    sys.path.insert(0, str(gui_module_dir))
    import urllib.request
    from codexbar_gui.server_launcher import start_server, kill_server

    success, proc = start_server(port=unused_port, wait=True, timeout=30)
    assert success, "Server should start"

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{unused_port}/usage", timeout=5
        ) as resp:
            data = json.loads(resp.read())
            assert isinstance(data, list)
    finally:
        kill_server()


# ---------------------------------------------------------------------------
# Test: Shared config file path
# ---------------------------------------------------------------------------

def test_shared_config_path(cli_module_dir: Path, gui_module_dir: Path):
    """Both CLI and GUI should reference the same config path."""
    sys.path.insert(0, str(cli_module_dir))
    sys.path.insert(0, str(gui_module_dir))
    from codexbar_usage.config import config_path
    # The GUI config_dialog imports PySide6 which isn't available in all envs,
    # so we verify the path directly from the source file.
    config_dialog_source = (gui_module_dir / "codexbar_gui" / "config_dialog.py").read_text()
    assert '_CONFIG_FILE = _CONFIG_DIR / "config.json"' in config_dialog_source
    assert 'Path.home() / ".config" / "codexbar"' in config_dialog_source
    # Verify they point to the same location
    expected = Path.home() / ".config" / "codexbar" / "config.json"
    assert config_path() == expected
