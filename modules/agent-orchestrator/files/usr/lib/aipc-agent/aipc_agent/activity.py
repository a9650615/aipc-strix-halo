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
# Overlay body (glass HUD). Native notify-send is a short fallback only.
_OVERLAY_BODY = int(os.environ.get("AIPC_OVERLAY_BODY_CHARS", "2500"))
_NOTIFY_BODY = int(os.environ.get("AIPC_NOTIFY_BODY_CHARS", "320"))
_ACTIVITY_CHARS = int(os.environ.get("AIPC_ACTIVITY_CHARS", "240"))


def _clip_sentence(text: str, limit: int) -> str:
    """Prefer end at punctuation within limit; keep trailing media block if any."""
    s = (text or "").strip()
    if not s:
        return ""
    if len(s) <= limit:
        return s
    # Preserve multi-media list when present (HUD needs full https lines)
    media_marks = ("（相關媒體）", "(相關媒體)", "相關媒體")
    media_i = -1
    for m in media_marks:
        j = s.find(m)
        if j >= 0:
            media_i = j if media_i < 0 else min(media_i, j)
    if media_i >= 0:
        media = s[media_i:]
        head = s[:media_i].rstrip()
        # Always try to keep media; shrink head first
        budget = max(80, limit - len(media) - 4)
        if len(head) > budget:
            cut = head[: budget - 1]
            for sep in ("。", "！", "？", "\n", ".", "!", "?"):
                i = cut.rfind(sep)
                if i >= max(20, budget // 4):
                    cut = cut[: i + 1]
                    break
            else:
                cut = cut.rstrip("，,、;； ") + "…"
            head = cut
        out = (head + "\n\n" + media).strip()
        if len(out) <= limit + 400:  # media block may slightly exceed soft limit
            return out
    cut = s[: limit - 1]
    for sep in ("。", "！", "？", "；", ".", "!", "?", "\n", "，", ","):
        i = cut.rfind(sep)
        if i >= max(24, limit // 3):
            return cut[: i + 1]
    return cut.rstrip("，,、;； ") + "…"


def _should_desktop_notify(*, force: bool = False) -> bool:
    """Native notify-send only when forced or overlay HUD is unavailable.

    AIPC_DESKTOP_NOTIFY=auto|0|1  (default auto)
    """
    mode = (os.environ.get("AIPC_DESKTOP_NOTIFY") or "auto").strip().lower()
    if mode in ("0", "off", "false", "no", "never"):
        return False
    if mode in ("1", "on", "true", "yes", "force", "always"):
        return True
    # auto
    if force and os.environ.get("AIPC_DESKTOP_NOTIFY_FORCE", "0") in ("1", "true", "yes"):
        return True
    try:
        from aipc_agent import ux_bridge

        if ux_bridge.overlay_alive():
            return False
    except Exception:
        pass
    return True


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
    """Update session + overlay; native notify only if HUD is down."""
    detail_s = _clip_sentence(detail or "處理中…", _ACTIVITY_CHARS)
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
    if not _should_desktop_notify(force=force_notify):
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
        task_jobs._notify_desktop(title, _clip_sentence(detail_s, _NOTIFY_BODY))
    except Exception:
        pass


def complete_notify(
    session_id: str,
    title: str,
    body: str,
    *,
    feedback_hint: bool = False,
) -> None:
    """Glass HUD primary; native notify only when overlay is unavailable.

    feedback_hint: append short cue so user can reject a bad Hermes answer.
    """
    body_s = (body or "").strip()
    if feedback_hint and body_s and "不对" not in body_s and "不對" not in body_s:
        cue = "\n\n（不对？下句说「不对」可反馈）"
        body_s = _clip_sentence(body_s, max(80, _OVERLAY_BODY - len(cue))) + cue
    else:
        body_s = _clip_sentence(body_s or "完成", _OVERLAY_BODY)
    # HUD first (long body)
    try:
        from aipc_agent import ux_bridge

        ux_bridge.finish_answer(
            body_s or body or "完成",
            source=f"session:{session_id}",
            hold_s=90.0 if feedback_hint else 60.0,
        )
    except Exception:
        try:
            from aipc_agent import ux_bridge

            ux_bridge.progress(
                _clip_sentence(body or "完成", _OVERLAY_BODY),
                state="done",
                source=f"session:{session_id}",
            )
        except Exception:
            pass
    # Native bubble only if HUD down
    if _should_desktop_notify():
        try:
            from aipc_agent import task_jobs

            task_jobs._notify_desktop(
                title[:80] or "AIPC 完成",
                _clip_sentence(body_s, _NOTIFY_BODY),
            )
        except Exception:
            pass
    try:
        from aipc_agent import session_registry

        session_registry.touch(
            session_id,
            status="active",
            activity=_clip_sentence(body or "完成", _ACTIVITY_CHARS),
            clear_job=True,
        )
    except Exception:
        pass
