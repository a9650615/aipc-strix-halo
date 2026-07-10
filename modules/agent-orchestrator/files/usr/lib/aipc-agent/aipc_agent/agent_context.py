"""Short-term multi-turn context per (session_id, agent_lane).

Complements mem0 long-term memories. STM is **disk-backed** so uvicorn
multi-worker processes share the same session history (updated_ts merge).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from aipc_agent.memory import agent_lane

_LOCK = threading.Lock()
# {f"{session}|{lane}": {"turns": [...], "ts": float, "agent": str}}
_BUF: dict[str, dict[str, Any]] = {}

MAX_TURNS = int(os.environ.get("AIPC_AGENT_CTX_TURNS", "12"))
TTL_S = float(os.environ.get("AIPC_AGENT_CTX_TTL_S", "1800"))
_PERSIST = os.environ.get("AIPC_AGENT_CTX_PERSIST", "1") not in ("0", "false", "no")
_DIR = Path(os.environ.get("AIPC_AGENT_CTX_DIR", "/var/lib/aipc-agent/stm"))


def _key(session_id: str, agent: str) -> str:
    return f"{(session_id or 'default').strip()}|{agent_lane(agent)}"


def _safe_name(k: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in k)[:120]


def _path(k: str) -> Path:
    return _DIR / f"{_safe_name(k)}.json"


def _load_key(k: str) -> dict[str, Any] | None:
    if not _PERSIST:
        return None
    p = _path(k)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _save_key(k: str, item: dict[str, Any]) -> None:
    if not _PERSIST:
        return
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        p = _path(k)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        print(f"aipc-agent: stm persist fail: {exc}", flush=True)


def _unlink_key(k: str) -> None:
    if not _PERSIST:
        return
    try:
        p = _path(k)
        if p.is_file():
            p.unlink()
    except OSError:
        pass


def _file_lock(k: str):
    """Cross-process exclusive lock for merge+write (best-effort)."""
    if not _PERSIST:
        return _null_lock()
    try:
        import fcntl
    except ImportError:
        return _null_lock()
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        lock_path = _DIR / f"{_safe_name(k)}.lock"
        fh = open(lock_path, "a+", encoding="utf-8")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        return fh
    except OSError:
        return _null_lock()


class _null_lock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        pass


def _merge_item(k: str) -> dict[str, Any] | None:
    """Return freshest item for key (disk vs RAM), drop if TTL expired."""
    disk = _load_key(k)
    with _LOCK:
        mem = _BUF.get(k)
        best = None
        if disk and mem:
            if float(disk.get("ts") or 0) >= float(mem.get("ts") or 0):
                best = disk
                _BUF[k] = disk
            else:
                best = mem
        elif disk:
            best = disk
            _BUF[k] = disk
        elif mem:
            best = mem
        if not best:
            return None
        if time.time() - float(best.get("ts") or 0) > TTL_S:
            _BUF.pop(k, None)
            _unlink_key(k)
            return None
        return best


def get_turns(session_id: str, agent: str) -> list[dict[str, str]]:
    k = _key(session_id, agent)
    item = _merge_item(k)
    if not item:
        return []
    return list(item.get("turns") or [])


def append_turn(session_id: str, agent: str, role: str, content: str) -> None:
    text = (content or "").strip()
    if not text:
        return
    k = _key(session_id, agent)
    lane = agent_lane(agent)
    # Cross-process lock so two workers don't clobber each other's turns
    lock_fh = _file_lock(k)
    try:
        prior = _merge_item(k)
        with _LOCK:
            item = prior or _BUF.get(k) or {
                "turns": [],
                "ts": time.time(),
                "agent": lane,
            }
            turns: list = list(item.get("turns") or [])
            turns.append({"role": role, "content": text[:2000]})
            item["turns"] = turns[-MAX_TURNS:]
            item["ts"] = time.time()
            item["agent"] = lane
            _BUF[k] = item
            to_save = dict(item)
            to_save["turns"] = list(item["turns"])
        _save_key(k, to_save)
    finally:
        try:
            import fcntl

            if hasattr(lock_fh, "fileno"):
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                lock_fh.close()
        except Exception:
            try:
                lock_fh.close()
            except Exception:
                pass


def clear(session_id: str, agent: str | None = None) -> None:
    """Clear one lane or all lanes for a session."""
    sid = (session_id or "default").strip()
    keys: list[str] = []
    with _LOCK:
        if agent:
            k = _key(sid, agent)
            _BUF.pop(k, None)
            keys = [k]
        else:
            prefix = f"{sid}|"
            keys = [k for k in list(_BUF) if k.startswith(prefix)]
            for k in keys:
                _BUF.pop(k, None)
    for k in keys:
        _unlink_key(k)
    # Disk clear by filename prefix (workers may only have disk state)
    if _PERSIST and _DIR.is_dir():
        prefix = _safe_name(f"{sid}|")
        try:
            for p in _DIR.glob("*.json"):
                if p.stem.startswith(prefix):
                    try:
                        p.unlink()
                    except OSError:
                        pass
            for p in _DIR.glob("*.lock"):
                if p.stem.startswith(prefix):
                    try:
                        p.unlink()
                    except OSError:
                        pass
        except OSError:
            pass


def format_history(session_id: str, agent: str) -> str:
    turns = get_turns(session_id, agent)
    if not turns:
        return ""
    lines = []
    for t in turns:
        role = t.get("role") or "?"
        content = (t.get("content") or "")[:400]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)
