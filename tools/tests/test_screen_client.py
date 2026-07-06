from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from aipc_lib import screen_client

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PKG = REPO_ROOT / "modules" / "agent-gate" / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(GATE_PKG))

from aipc_agent_gate import server as gate_server  # noqa: E402


@pytest.fixture()
def running_gate(tmp_path: Path):
    """Real gate daemon on a tmp socket/db, exercising screen_client against
    the actual wire protocol (see test_gate_client.py's sibling fixture)."""
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


def test_grant_session_then_check(running_gate: str) -> None:
    r = screen_client.grant_session("300", sock_path=running_gate)
    assert "grant_id" in r and r["expires_at"] is not None

    from aipc_lib import gate_client

    chk = gate_client.send({"cmd": "check", "action": "screen-control"}, sock_path=running_gate)
    assert chk == {"allowed": True, "grant_id": r["grant_id"]}


def test_grant_session_rejects_non_integer_duration(running_gate: str) -> None:
    r = screen_client.grant_session("not-a-number", sock_path=running_gate)
    assert "error" in r


def test_grant_always_then_revoke(running_gate: str) -> None:
    r = screen_client.grant_always(sock_path=running_gate)
    assert r["task_id"] == screen_client.ALWAYS_TASK_ID and r["expires_at"] is None

    from aipc_lib import gate_client

    chk = gate_client.send({"cmd": "check", "action": "screen-control"}, sock_path=running_gate)
    assert chk["allowed"] is True

    rev = screen_client.revoke(sock_path=running_gate)
    assert rev == {"revoked": 1}

    chk2 = gate_client.send({"cmd": "check", "action": "screen-control"}, sock_path=running_gate)
    assert chk2 == {"allowed": False, "grant_id": None}


def test_revoke_with_no_active_always_grant_is_a_noop(running_gate: str) -> None:
    rev = screen_client.revoke(sock_path=running_gate)
    assert rev == {"revoked": 0}
