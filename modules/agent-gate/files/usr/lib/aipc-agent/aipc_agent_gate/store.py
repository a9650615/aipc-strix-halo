"""In-memory grant store for aipc-agent-gate (phase-4-agent#5.1), backed by
SQLite so grants survive a daemon restart. See server.py's module docstring
for the RPC wire format any caller (CLI, agent-tools-files, a future
agent-screen-control) speaks over /run/aipc-agent-gate.sock.
"""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

DEFAULT_DB_PATH = "/var/lib/aipc-agent/gate.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grants (
    grant_id TEXT PRIMARY KEY,
    actions TEXT NOT NULL,
    scope TEXT NOT NULL,
    expires_at REAL,
    task_id TEXT,
    granted_at REAL NOT NULL
)
"""


class GrantStore:
    """Grants live in `self._grants` (grant_id -> dict) for check()'s hot
    path -- no SQLite hit there. SQLite is only touched by grant/revoke and
    by the periodic sweep (see sweep_expired)."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._grants: dict[str, dict] = {}
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        self._load()

    def _load(self) -> None:
        """Load still-valid grants back into memory on daemon start. Task-
        scoped grants have no time bound (only an explicit revoke ends
        them) so all of them load; session-scoped grants load only if
        their expiry hasn't already passed."""
        now = time.time()
        cur = self._conn.execute(
            "SELECT grant_id, actions, scope, expires_at, task_id, granted_at FROM grants"
        )
        for grant_id, actions, scope, expires_at, task_id, granted_at in cur.fetchall():
            if scope == "session" and (expires_at is None or expires_at <= now):
                continue
            self._grants[grant_id] = {
                "actions": json.loads(actions),
                "scope": scope,
                "expires_at": expires_at,
                "task_id": task_id,
                "granted_at": granted_at,
            }

    def grant(
        self,
        actions: list[str],
        scope: str,
        duration_seconds: int | None = None,
        task_id: str | None = None,
    ) -> dict:
        if scope not in ("session", "task"):
            raise ValueError(f"scope must be 'session' or 'task', got {scope!r}")
        if not actions:
            raise ValueError("actions must be a non-empty list")

        now = time.time()
        expires_at = None
        if scope == "session":
            if duration_seconds is None:
                raise ValueError("session scope requires duration_seconds")
            expires_at = now + duration_seconds
        elif not task_id:
            raise ValueError("task scope requires task_id")

        grant_id = uuid.uuid4().hex
        entry = {
            "actions": list(actions),
            "scope": scope,
            "expires_at": expires_at,
            "task_id": task_id,
            "granted_at": now,
        }
        with self._lock:
            self._grants[grant_id] = entry
            self._conn.execute(
                "INSERT INTO grants (grant_id, actions, scope, expires_at, task_id, granted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (grant_id, json.dumps(entry["actions"]), scope, expires_at, task_id, now),
            )
            self._conn.commit()
        return {"grant_id": grant_id, "expires_at": expires_at, "task_id": task_id}

    def revoke(self, grant_id: str | None = None, task_id: str | None = None) -> int:
        if grant_id:
            with self._lock:
                existed = self._grants.pop(grant_id, None) is not None
                self._conn.execute("DELETE FROM grants WHERE grant_id = ?", (grant_id,))
                self._conn.commit()
            return 1 if existed else 0
        if task_id:
            with self._lock:
                match_ids = [
                    gid for gid, e in self._grants.items()
                    if e["scope"] == "task" and e["task_id"] == task_id
                ]
                for gid in match_ids:
                    del self._grants[gid]
                self._conn.execute(
                    "DELETE FROM grants WHERE scope = 'task' AND task_id = ?", (task_id,)
                )
                self._conn.commit()
            return len(match_ids)
        raise ValueError("revoke requires grant_id or task_id")

    def check(self, action: str) -> tuple[bool, str | None]:
        """Hot path: in-memory scan only, no SQLite. An expired session
        grant is denied purely by comparing expires_at -- sweep_expired is
        hygiene, not correctness."""
        now = time.time()
        with self._lock:
            for grant_id, entry in self._grants.items():
                if action not in entry["actions"]:
                    continue
                if entry["scope"] == "session" and entry["expires_at"] is not None and entry["expires_at"] <= now:
                    continue
                return True, grant_id
        return False, None

    def status(self) -> list[dict]:
        now = time.time()
        with self._lock:
            return [
                {"grant_id": gid, **entry}
                for gid, entry in self._grants.items()
                if entry["scope"] == "task" or entry["expires_at"] is None or entry["expires_at"] > now
            ]

    def sweep_expired(self) -> int:
        """ponytail: periodic hygiene sweep (server.py's background thread
        calls this every 30s), not required for check()'s correctness --
        that's a timestamp comparison. Purges expired session grants from
        memory and SQLite so a long-lived daemon doesn't accumulate dead
        rows. Upgrade path if this ever matters at scale: index by action
        instead of a full dict scan -- irrelevant at this daemon's grant
        counts (single-user machine, low tens of grants at most)."""
        now = time.time()
        with self._lock:
            expired = [
                gid for gid, e in self._grants.items()
                if e["scope"] == "session" and e["expires_at"] is not None and e["expires_at"] <= now
            ]
            for gid in expired:
                del self._grants[gid]
            if expired:
                self._conn.executemany(
                    "DELETE FROM grants WHERE grant_id = ?", [(g,) for g in expired]
                )
                self._conn.commit()
        return len(expired)

    def close(self) -> None:
        self._conn.close()
