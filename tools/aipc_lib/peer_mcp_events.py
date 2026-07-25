"""Small stdlib contract for peer-agents MCP progress events."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 4000
MAX_JOURNAL_BYTES = 5_000_000
_WRITE_LOCK = threading.Lock()


def _journal_path(hermes_home: Path) -> Path:
    return hermes_home / "peer-agents" / "events.jsonl"


def clip_output(value: object, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = str(value or "")
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    if len(text) <= limit:
        return text
    return text[-max(1, limit - 1) :] + "…"


def _trim_journal(path: Path) -> None:
    try:
        if path.stat().st_size <= MAX_JOURNAL_BYTES:
            return
        data = path.read_bytes()[-MAX_JOURNAL_BYTES // 2 :]
        if b"\n" in data:
            data = data.split(b"\n", 1)[1]
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.chmod(0o600)
        os.replace(tmp, path)
    except OSError:
        return


def append_event(hermes_home: Path, event: dict[str, Any]) -> dict[str, Any]:
    directory = hermes_home / "peer-agents"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / "events.jsonl"
    clean = dict(event)
    clean.setdefault("schema", 1)
    clean.setdefault("event_id", str(uuid.uuid4()))
    clean.setdefault("ts", time.time())
    if "output_tail" in clean:
        clean["output_tail"] = clip_output(clean["output_tail"])
    if "error" in clean:
        clean["error"] = clip_output(clean["error"])
    payload = (json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    with _WRITE_LOCK:
        _trim_journal(path)
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, payload)
        finally:
            os.close(fd)
    return clean


def fold_events(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    latest: dict[str, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or not event.get("agent_id"):
                    continue
                agent_id = str(event["agent_id"])
                current = latest.get(agent_id)
                if current and float(event.get("ts") or 0) < float(current.get("ts") or 0):
                    continue
                merged = dict(current or {})
                merged.update(event)
                latest[agent_id] = merged
    except OSError:
        return []
    rows = sorted(latest.values(), key=lambda row: float(row.get("ts") or 0), reverse=True)
    return rows[: max(0, int(limit))]


def pid_alive(pid: object) -> bool:
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def terminal_status(kind: str, exit_code: int | None = None) -> str:
    if kind == "stopped":
        return "stopped"
    if kind in {"failed", "timeout", "timed_out"}:
        return "failed"
    if kind in {"finished", "completed"}:
        return "completed" if exit_code in (None, 0) else "failed"
    return "failed"
