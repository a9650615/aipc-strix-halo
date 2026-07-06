"""Append-only audit log for aipc-agent-gate (phase-4-agent#5.5).

One JSON object per line at /var/log/aipc-agent-gate.jsonl, never rewritten.
Every grant, every check (allow and deny), and every revoke appends exactly
one line here.
"""

import json
import sys
import threading
import time
from pathlib import Path

DEFAULT_LOG_PATH = "/var/log/aipc-agent-gate.jsonl"

_lock = threading.Lock()


def append(event: str, log_path: str | None = None, **fields) -> None:
    # log_path resolves against the module-level default at call time (not
    # bind time) so tests can monkeypatch DEFAULT_LOG_PATH.
    path = log_path if log_path is not None else DEFAULT_LOG_PATH
    row = {"ts": time.time(), "event": event, **fields}
    line = json.dumps(row, sort_keys=True) + "\n"
    try:
        with _lock:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except OSError as e:
        # Audit logging is best-effort: a disk-full or permission problem on
        # the log must not take down grant/check/revoke, the actual safety
        # mechanism. Surface it on stderr (systemd journal) instead.
        print(f"aipc-agent-gate: audit log write failed: {e}", file=sys.stderr)
