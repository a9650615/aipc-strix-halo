"""First-class conversation sessions with STM binding and activity lines.

Open sessions keep short-term memory (agent_context) until complete/farewell.
Long jobs attach job_id and push last_activity for overlay/portal/notify.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}

STATUSES = frozenset({"active", "working", "waiting_user", "done", "failed"})
DEFAULT_VOICE_ID = os.environ.get("AIPC_VOICE_SESSION_ID", "voice-assistant")
_PERSIST = os.environ.get("AIPC_SESSION_PERSIST", "1") not in ("0", "false", "no")
_DIR = Path(os.environ.get("AIPC_SESSION_DIR", "/var/lib/aipc-agent/sessions"))
_IDLE_S = float(os.environ.get("AIPC_SESSION_IDLE_S", "1800"))
_MAX = int(os.environ.get("AIPC_SESSION_MAX", "40"))


def _now() -> float:
    return time.time()


def _path(sid: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in sid)[:80]
    return _DIR / f"{safe}.json"


def _persist(sess: dict[str, Any]) -> None:
    if not _PERSIST:
        return
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        p = _path(str(sess.get("id") or "x"))
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(sess, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _trim_locked() -> None:
    if len(_SESSIONS) <= _MAX:
        return
    # Drop oldest done/failed first
    items = sorted(
        _SESSIONS.items(),
        key=lambda kv: (
            0 if kv[1].get("status") in ("done", "failed") else 1,
            float(kv[1].get("updated_ts") or 0),
        ),
    )
    while len(_SESSIONS) > _MAX and items:
        jid, _ = items.pop(0)
        _SESSIONS.pop(jid, None)


def get(session_id: str) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    # Always prefer disk when newer (uvicorn multi-worker).
    if _PERSIST:
        p = _path(sid)
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id"):
                    disk_ts = float(data.get("updated_ts") or 0)
                    with _LOCK:
                        cur = _SESSIONS.get(sid)
                        if not cur or disk_ts >= float(cur.get("updated_ts") or 0):
                            _SESSIONS[sid] = data
                            return dict(data)
            except (OSError, json.JSONDecodeError):
                pass
    with _LOCK:
        s = _SESSIONS.get(sid)
        return dict(s) if s else None


def _load_all_from_disk() -> None:
    """Merge disk into RAM. Prefer newer updated_ts (multi-worker safe)."""
    if not _PERSIST or not _DIR.is_dir():
        return
    try:
        for p in _DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or not data.get("id"):
                continue
            sid = str(data["id"])
            disk_ts = float(data.get("updated_ts") or 0)
            with _LOCK:
                cur = _SESSIONS.get(sid)
                if not cur or disk_ts >= float(cur.get("updated_ts") or 0):
                    _SESSIONS[sid] = data
    except OSError:
        pass


def list_sessions(*, include_done: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    _load_all_from_disk()
    with _LOCK:
        items = list(_SESSIONS.values())
    if not include_done:
        items = [s for s in items if s.get("status") not in ("done", "failed")]
    items.sort(key=lambda x: float(x.get("updated_ts") or 0), reverse=True)
    return [dict(x) for x in items[: max(1, limit)]]


def open_or_resume(
    session_id: str | None = None,
    *,
    source: str = "api",
    title: str = "",
) -> dict[str, Any]:
    """Return an open session; create if missing or previously done."""
    sid = (session_id or "").strip() or DEFAULT_VOICE_ID
    now = _now()
    with _LOCK:
        s = _SESSIONS.get(sid)
        if s and s.get("status") not in ("done", "failed"):
            # idle reopen check — still open but stale: keep STM unless past idle
            s["updated_ts"] = now
            s["source"] = source or s.get("source") or "api"
            if title and not s.get("title"):
                s["title"] = title[:80]
            _SESSIONS[sid] = s
            _persist(s)
            return dict(s)
        # create / reopen
        s = {
            "id": sid,
            "status": "active",
            "title": (title or "")[:80],
            "created_ts": now,
            "updated_ts": now,
            "source": source or "api",
            "job_id": None,
            "pending": None,
            "last_activity": "會話已開啟",
            "progress_pct": None,
            "turn_count": 0,
        }
        _SESSIONS[sid] = s
        _trim_locked()
        _persist(s)
        return dict(s)


def touch(
    session_id: str,
    *,
    status: str | None = None,
    activity: str | None = None,
    job_id: str | None = None,
    title: str | None = None,
    progress_pct: float | None = None,
    pending: Any = None,
    clear_job: bool = False,
    bump_turn: bool = False,
) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        s = _SESSIONS.get(sid)
        if not s:
            return None
        if status and status in STATUSES:
            s["status"] = status
        if activity is not None:
            s["last_activity"] = (activity or "")[:160]
        if job_id is not None:
            s["job_id"] = job_id
        if clear_job:
            s["job_id"] = None
        if title:
            s["title"] = title[:80]
        if progress_pct is not None:
            s["progress_pct"] = progress_pct
        if pending is not None:
            s["pending"] = pending
        if bump_turn:
            s["turn_count"] = int(s.get("turn_count") or 0) + 1
        s["updated_ts"] = _now()
        _SESSIONS[sid] = s
        _persist(s)
        return dict(s)


def complete(session_id: str, *, reason: str = "done", failed: bool = False) -> dict[str, Any] | None:
    """Mark session terminal; caller should consolidate STM then clear."""
    sid = (session_id or "").strip()
    if not sid:
        return None
    st = "failed" if failed else "done"
    with _LOCK:
        s = _SESSIONS.get(sid) or {
            "id": sid,
            "created_ts": _now(),
            "source": "api",
            "title": "",
        }
        s["status"] = st
        s["last_activity"] = f"會話結束（{reason}）"[:160]
        s["job_id"] = None
        s["pending"] = None
        s["updated_ts"] = _now()
        s["ended_reason"] = reason
        _SESSIONS[sid] = s
        _persist(s)
        out = dict(s)
    # Best-effort STM clear after consolidate is caller's job; we clear here too
    # if consolidate already ran — safe to clear agent_context.
    try:
        from aipc_agent import agent_context, memory

        try:
            memory.consolidate_session(sid, agent=memory.AGENT_CHAT, reason=reason)
        except Exception:
            pass
        agent_context.clear(sid)
    except Exception:
        pass
    return out


def bind_job(session_id: str, job_id: str, *, activity: str = "") -> None:
    touch(
        session_id,
        status="working",
        job_id=job_id,
        activity=activity or f"任務 {job_id} 執行中…",
    )


def activity_snapshot(limit: int = 15) -> list[dict[str, Any]]:
    """Open sessions + running jobs for portal Activity card."""
    from aipc_agent import task_jobs

    sessions = list_sessions(include_done=False, limit=limit)
    jobs = [j for j in task_jobs.job_list(limit=limit) if j.get("status") == "running"]
    # merge job progress into matching sessions
    by_job = {j.get("job_id"): j for j in jobs}
    out = []
    for s in sessions:
        row = dict(s)
        jid = s.get("job_id")
        if jid and jid in by_job:
            j = by_job[jid]
            row["last_activity"] = j.get("last_progress") or j.get("detail") or row.get(
                "last_activity"
            )
            row["job_status"] = j.get("status")
        out.append(row)
    # orphan running jobs without session entry
    sess_jobs = {s.get("job_id") for s in sessions if s.get("job_id")}
    for j in jobs:
        if j.get("job_id") in sess_jobs:
            continue
        out.append(
            {
                "id": f"job:{j.get('job_id')}",
                "status": "working",
                "title": task_jobs.worker_label(str(j.get("worker") or "")),
                "last_activity": j.get("last_progress") or j.get("detail") or "",
                "job_id": j.get("job_id"),
                "source": "job",
                "updated_ts": j.get("updated") or j.get("started"),
            }
        )
    out.sort(key=lambda x: float(x.get("updated_ts") or 0), reverse=True)
    return out[:limit]


def ensure_voice_session() -> dict[str, Any]:
    return open_or_resume(DEFAULT_VOICE_ID, source="voice")
