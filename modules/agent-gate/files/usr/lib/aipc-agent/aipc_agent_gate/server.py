"""UNIX-socket RPC server for aipc-agent-gate (phase-4-agent#5.1-5.5).

Wire protocol: newline-delimited JSON, one request per line in, one
response per line out, over /run/aipc-agent-gate.sock (AF_UNIX,
SOCK_STREAM). Single-user trusted machine (CLAUDE.md §0/§6, design.md D5)
-- no auth on the socket itself; it's chmod 0666 so a non-root `aipc agent
gate ...` CLI invocation works without sudo.

Requests (one JSON object per line):
  {"cmd": "grant", "actions": [...], "scope": "session"|"task",
   "duration_seconds": <int, session only>, "task_id": <str, task only>}
    -> {"grant_id": "...", "expires_at": <float>|null, "task_id": <str>|null}
  {"cmd": "revoke", "grant_id": "..."} or {"cmd": "revoke", "task_id": "..."}
    -> {"revoked": <count>}
  {"cmd": "check", "action": "screen-control"|<other action name>}
    -> {"allowed": true|false, "grant_id": <str>|null}
  {"cmd": "status"}
    -> {"grants": [{"grant_id", "actions", "scope", "expires_at", "task_id",
                     "granted_at"}, ...]}
Any error (bad cmd, missing/invalid field) -> {"error": "..."}, connection
still gets exactly one response line.
"""

import json
import socketserver
import sys
import threading
from pathlib import Path

from aipc_agent_gate import audit
from aipc_agent_gate.store import DEFAULT_DB_PATH, GrantStore

SOCKET_PATH = "/run/aipc-agent-gate.sock"
SWEEP_INTERVAL_SECONDS = 30


def handle_request(store: GrantStore, req: dict) -> dict:
    cmd = req.get("cmd")

    if cmd == "grant":
        result = store.grant(
            actions=req.get("actions") or [],
            scope=req.get("scope"),
            duration_seconds=req.get("duration_seconds"),
            task_id=req.get("task_id"),
        )
        audit.append(
            "grant", grant_id=result["grant_id"], scope=req.get("scope"),
            actions=req.get("actions"), outcome="granted",
        )
        return result

    if cmd == "revoke":
        count = store.revoke(grant_id=req.get("grant_id"), task_id=req.get("task_id"))
        audit.append(
            "revoke", grant_id=req.get("grant_id"), task_id=req.get("task_id"),
            count=count, outcome="revoked",
        )
        return {"revoked": count}

    if cmd == "check":
        action = req.get("action")
        allowed, grant_id = store.check(action)
        audit.append(
            "check", action=action, grant_id=grant_id,
            outcome="allowed" if allowed else "denied",
        )
        return {"allowed": allowed, "grant_id": grant_id}

    if cmd == "status":
        return {"grants": store.status()}

    raise ValueError(f"unknown cmd {cmd!r}")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline()
        if not line:
            return
        try:
            req = json.loads(line)
            resp = handle_request(self.server.store, req)
        except (ValueError, TypeError, KeyError) as e:
            resp = {"error": str(e)}
        self.wfile.write((json.dumps(resp) + "\n").encode())


class GateServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: str, store: GrantStore):
        self.store = store
        Path(socket_path).unlink(missing_ok=True)
        super().__init__(socket_path, _Handler)
        Path(socket_path).chmod(0o666)  # single-user trust model, see module docstring


def _sweep_loop(store: GrantStore, stop: threading.Event, interval: int = SWEEP_INTERVAL_SECONDS) -> None:
    while not stop.wait(interval):
        store.sweep_expired()


def main(socket_path: str = SOCKET_PATH, db_path: str = DEFAULT_DB_PATH) -> None:
    store = GrantStore(db_path)
    stop = threading.Event()
    sweeper = threading.Thread(target=_sweep_loop, args=(store, stop), daemon=True)
    sweeper.start()
    server = GateServer(socket_path, store)
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
        store.close()


def self_test() -> None:
    """ponytail: one runnable check driving GrantStore + handle_request
    directly (no real socket) -- the socket is a thin transport, exercising
    the real dispatch logic is what matters and is far less flaky than
    binding a UNIX socket in a test. Covers: session grant, allow-then-deny
    on expiry (duration_seconds=0 forces immediate expiry), explicit
    revoke, task-scope grant + bulk revoke-by-task_id, and reload-from-
    SQLite across a simulated restart."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "gate.db")
        store = GrantStore(db_path)
        # self-test runs unprivileged; redirect the audit log out of
        # /var/log (root-owned) for the duration of this check.
        orig_log_path = audit.DEFAULT_LOG_PATH
        audit.DEFAULT_LOG_PATH = str(Path(tmp) / "audit.jsonl")

        # session grant with duration_seconds=0 must be immediately expired
        r = handle_request(
            store, {"cmd": "grant", "actions": ["screen-control"], "scope": "session", "duration_seconds": 0}
        )
        assert "grant_id" in r and r["expires_at"] is not None, r
        chk = handle_request(store, {"cmd": "check", "action": "screen-control"})
        assert chk == {"allowed": False, "grant_id": None}, chk

        # session grant with a real duration must be allowed, then revocable
        r2 = handle_request(
            store, {"cmd": "grant", "actions": ["screen-control"], "scope": "session", "duration_seconds": 300}
        )
        chk2 = handle_request(store, {"cmd": "check", "action": "screen-control"})
        assert chk2 == {"allowed": True, "grant_id": r2["grant_id"]}, chk2
        rev = handle_request(store, {"cmd": "revoke", "grant_id": r2["grant_id"]})
        assert rev == {"revoked": 1}, rev
        chk3 = handle_request(store, {"cmd": "check", "action": "screen-control"})
        assert chk3 == {"allowed": False, "grant_id": None}, chk3

        # task-scope grant + bulk revoke by task_id
        r3 = handle_request(
            store, {"cmd": "grant", "actions": ["git-push"], "scope": "task", "task_id": "refactor-x"}
        )
        assert r3["task_id"] == "refactor-x" and r3["expires_at"] is None, r3
        chk4 = handle_request(store, {"cmd": "check", "action": "git-push"})
        assert chk4["allowed"] is True, chk4
        rev2 = handle_request(store, {"cmd": "revoke", "task_id": "refactor-x"})
        assert rev2 == {"revoked": 1}, rev2
        chk5 = handle_request(store, {"cmd": "check", "action": "git-push"})
        assert chk5 == {"allowed": False, "grant_id": None}, chk5

        st = handle_request(store, {"cmd": "status"})
        assert st == {"grants": []}, st

        # unknown cmd raises ValueError (the socket handler turns this into
        # {"error": ...} -- see _Handler.handle -- but the raise itself is
        # what matters here)
        try:
            handle_request(store, {"cmd": "bogus"})
            raise AssertionError("unknown cmd did NOT raise")
        except ValueError:
            pass

        # a still-valid grant must reload from SQLite across a restart
        r4 = handle_request(
            store, {"cmd": "grant", "actions": ["email-send"], "scope": "session", "duration_seconds": 300}
        )
        store.close()
        store2 = GrantStore(db_path)
        assert store2.check("email-send") == (True, r4["grant_id"]), store2.check("email-send")
        store2.close()
        audit.DEFAULT_LOG_PATH = orig_log_path

    print("self-test passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    main()
