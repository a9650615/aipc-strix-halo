from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from aipc_lib import gate_client

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PKG = REPO_ROOT / "modules" / "agent-gate" / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(GATE_PKG))

from aipc_agent_gate import server as gate_server  # noqa: E402


@pytest.fixture()
def running_gate(tmp_path: Path):
    """Real gate daemon (real UNIX socket, real SQLite) on a tmp path --
    exercises gate_client.send() against the actual wire protocol, not a
    mock of it."""
    sock_path = str(tmp_path / "gate.sock")
    db_path = str(tmp_path / "gate.db")
    t = threading.Thread(target=gate_server.main, args=(sock_path, db_path), daemon=True)
    t.start()
    for _ in range(50):
        if Path(sock_path).exists():
            break
        time.sleep(0.02)
    else:
        pytest.fail("gate socket never appeared")
    yield sock_path


def test_grant_check_status_revoke_round_trip(running_gate: str) -> None:
    r = gate_client.send(
        {"cmd": "grant", "actions": ["screen-control"], "scope": "session", "duration_seconds": 300},
        sock_path=running_gate,
    )
    assert "grant_id" in r and r["expires_at"] is not None

    chk = gate_client.send({"cmd": "check", "action": "screen-control"}, sock_path=running_gate)
    assert chk == {"allowed": True, "grant_id": r["grant_id"]}

    st = gate_client.send({"cmd": "status"}, sock_path=running_gate)
    assert len(st["grants"]) == 1

    rev = gate_client.send({"cmd": "revoke", "grant_id": r["grant_id"]}, sock_path=running_gate)
    assert rev == {"revoked": 1}

    chk2 = gate_client.send({"cmd": "check", "action": "screen-control"}, sock_path=running_gate)
    assert chk2 == {"allowed": False, "grant_id": None}


def test_task_scope_bulk_revoke(running_gate: str) -> None:
    r = gate_client.send(
        {"cmd": "grant", "actions": ["git-push"], "scope": "task", "task_id": "t1"},
        sock_path=running_gate,
    )
    assert r["task_id"] == "t1" and r["expires_at"] is None

    rev = gate_client.send({"cmd": "revoke", "task_id": "t1"}, sock_path=running_gate)
    assert rev == {"revoked": 1}

    chk = gate_client.send({"cmd": "check", "action": "git-push"}, sock_path=running_gate)
    assert chk["allowed"] is False


def test_unknown_cmd_returns_error(running_gate: str) -> None:
    resp = gate_client.send({"cmd": "bogus"}, sock_path=running_gate)
    assert "error" in resp
