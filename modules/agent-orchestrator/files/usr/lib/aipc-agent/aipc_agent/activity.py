"""Activity bus: throttle desktop notifies + session activity lines."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

_LOCK = threading.Lock()
_LAST_NOTIFY: dict[str, float] = {}
_LAST_LABEL: dict[str, str] = {}
_MIN_GAP = float(os.environ.get("AIPC_ACTIVITY_NOTIFY_GAP_S", "8.0"))


def publish(
    session_id: str,
    detail: str,
    *,
    state: str = "working",
    phase: str = "",
    job_id: str | None = None,
    notify: bool = False,
    force_notify: bool = False,
    progress_pct: float | None = None,
) -> None:
    """Update session + overlay; optionally desktop-notify (throttled)."""
    detail_s = (detail or "處理中…")[:160]
    sid = (session_id or "").strip() or "default"
    try:
        from aipc_agent import session_registry

        session_registry.touch(
            sid,
            status="working" if state == "working" else None,
            activity=detail_s,
            job_id=job_id,
            progress_pct=progress_pct,
        )
    except Exception:
        pass
    try:
        from aipc_agent import ux_bridge

        ux_bridge.progress(detail_s, state=state, source=f"session:{sid}")
    except Exception:
        pass

    if not notify and not force_notify:
        return
    key = sid or job_id or "global"
    label = phase or detail_s[:40]
    now = time.time()
    with _LOCK:
        last_t = _LAST_NOTIFY.get(key, 0.0)
        last_l = _LAST_LABEL.get(key, "")
        if not force_notify and (now - last_t) < _MIN_GAP and label == last_l:
            return
        _LAST_NOTIFY[key] = now
        _LAST_LABEL[key] = label
    try:
        from aipc_agent import task_jobs

        title = "AIPC 進行中" if state == "working" else "AIPC"
        task_jobs._notify_desktop(title, detail_s[:200])
    except Exception:
        pass


def complete_notify(session_id: str, title: str, body: str) -> None:
    try:
        from aipc_agent import task_jobs

        task_jobs._notify_desktop(title[:80] or "AIPC 完成", (body or "")[:200])
    except Exception:
        pass
    try:
        from aipc_agent import session_registry

        session_registry.touch(
            session_id,
            status="active",
            activity=(body or "完成")[:160],
            clear_job=True,
        )
    except Exception:
        pass
