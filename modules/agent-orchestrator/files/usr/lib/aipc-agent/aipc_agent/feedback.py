"""User feedback on the last agent result (Hermes / tool turns).

After a Hermes answer, the user can say e.g. 不对 / 乱答 / 错了. We record the
feedback, avoid treating the prior turn as a good skill seed, and ack in-chat.

No domain allowlists — only negative/positive feedback phrasing.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_LAST: dict[str, dict[str, Any]] = {}

_STATE_DIR = Path(
    os.environ.get("AIPC_FEEDBACK_DIR", "/var/lib/aipc-agent/learning")
)
_STATE_FILE = _STATE_DIR / "last_results.json"
_TTL_S = float(os.environ.get("AIPC_FEEDBACK_TTL_S", "900"))

_NEG = (
    "不对",
    "不對",
    "错了",
    "錯了",
    "乱答",
    "亂答",
    "胡说",
    "胡說",
    "瞎说",
    "瞎說",
    "答错",
    "答錯",
    "不准",
    "不準",
    "错误",
    "錯誤",
    "feedback bad",
    "wrong answer",
    "incorrect",
    "not right",
    "that's wrong",
    "thats wrong",
)


def _load() -> dict[str, dict[str, Any]]:
    if not _STATE_FILE.is_file():
        return {}
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(_STATE_FILE)
    except OSError as exc:
        print(f"aipc-agent: feedback save fail: {exc}", flush=True)


def remember_result(
    session_id: str,
    *,
    user: str,
    reply: str,
    target: str = "hermes",
    trail: str = "",
    ok: bool = True,
) -> None:
    """Store last result for this session so user can give feedback next turn."""
    sid = (session_id or "").strip() or "default"
    row = {
        "ts": time.time(),
        "user": (user or "")[:400],
        "reply": (reply or "")[:1200],
        "target": target or "",
        "trail": (trail or "")[:2000],
        "ok": bool(ok),
        "feedback": None,
    }
    with _LOCK:
        data = _load()
        data[sid] = row
        # prune old
        now = time.time()
        data = {
            k: v
            for k, v in data.items()
            if isinstance(v, dict) and now - float(v.get("ts") or 0) < _TTL_S * 4
        }
        data[sid] = row
        _LAST[sid] = row
        _save(data)


def get_last(session_id: str) -> dict[str, Any] | None:
    """Last result for this session, else most recent across sessions (voice≠krunner)."""
    sid = (session_id or "").strip() or "default"
    now = time.time()
    with _LOCK:
        data = _load()
        # prefer in-memory then disk for this sid
        row = _LAST.get(sid) or data.get(sid)
        if isinstance(row, dict) and now - float(row.get("ts") or 0) <= _TTL_S:
            return row
        # Cross-channel: krunner answer then voice says「不对」must still hit.
        best: dict[str, Any] | None = None
        best_ts = 0.0
        for src in (_LAST, data):
            for k, v in src.items():
                if not isinstance(v, dict):
                    continue
                ts = float(v.get("ts") or 0)
                if now - ts > _TTL_S:
                    continue
                if v.get("feedback"):
                    continue  # already judged
                if ts >= best_ts:
                    best_ts = ts
                    best = dict(v)
                    best["_sid"] = k
        return best


def is_negative_feedback(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 80:
        return False
    low = t.lower()
    if any(n in t or n.lower() in low for n in _NEG):
        return True
    # short pure rejections
    if re.fullmatch(r"(不对|不對|错了|錯了|乱答|亂答|不行)[。.!！?？]*", t):
        return True
    return False


def apply_negative_feedback(session_id: str, text: str) -> str:
    """Record negative feedback; best-effort unlearn last path skill if fresh."""
    last = get_last(session_id)
    if not last:
        return "没有可反馈的上一条结果。请先问一个问题，再在回答后说「不对」。"

    with _LOCK:
        data = _load()
        # Write onto the session that owns the result (may be krunner while user is voice)
        sid = str(last.get("_sid") or (session_id or "").strip() or "default")
        row = dict(data.get(sid) or last)
        row.pop("_sid", None)
        row["feedback"] = "negative"
        row["feedback_text"] = (text or "")[:120]
        row["feedback_ts"] = time.time()
        data[sid] = row
        _LAST[sid] = row
        # also mirror under current session so same-channel re-check sees it
        cur = (session_id or "").strip() or "default"
        if cur != sid:
            mirror = dict(row)
            data[cur] = mirror
            _LAST[cur] = mirror
        _save(data)

    try:
        from aipc_agent import episode_log

        episode_log.append(
            {
                "kind": "user_feedback",
                "feedback": "negative",
                "session_id": session_id,
                "user": text[:120],
                "about_user": (last.get("user") or "")[:200],
                "about_reply": (last.get("reply") or "")[:300],
                "target": last.get("target"),
            }
        )
    except Exception:
        pass

    # Do not keep a just-learned skill if user rejects the turn (PATH may be poison)
    try:
        from aipc_agent import skill_store
        from pathlib import Path

        root = skill_store.write_root()
        # Only remove machine-grown web-lookup-path if updated in last few minutes
        meta_path = root / "web-lookup-path" / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            age = time.time() - float(meta.get("updated_ts") or 0)
            if age < 600:
                # rewrite body note: last feedback rejected — keep hosts but mark caution
                skill_md = root / "web-lookup-path" / "SKILL.md"
                if skill_md.is_file():
                    body = skill_md.read_text(encoding="utf-8")
                    note = (
                        "\n\n## User feedback\n"
                        f"- Recent turn marked wrong by user ({time.strftime('%Y-%m-%d %H:%M')}). "
                        "Prefer re-verify with tools; do not trust the last spoken answer alone.\n"
                    )
                    if "User feedback" not in body:
                        skill_md.write_text(body.rstrip() + note, encoding="utf-8")
                print(
                    "aipc-agent: feedback marked recent web-lookup-path (not deleted)",
                    flush=True,
                )
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: feedback skill mark fail: {exc}", flush=True)

    return (
        "已记下：上一条回答不可靠，我不会把它当正确答案。"
        "你可以再说一次要查什么，我会重新用工具核实。"
    )
