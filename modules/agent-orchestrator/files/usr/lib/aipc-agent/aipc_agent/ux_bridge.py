"""Best-effort UX progress for tool / Hermes work → overlay + status file.

Orchestrator often runs as root; desktop overlay listens on the user session
socket + $XDG_RUNTIME_DIR/aipc-voice-state.json. Never raises — chat must not
fail if UX is down.
"""
from __future__ import annotations

import json
import os
import pwd
import socket
import time
from pathlib import Path
from typing import Any


def _desktop_uid() -> int:
    try:
        name = os.environ.get("AIPC_PRIMARY_USER") or os.environ.get("AIPC_HERMES_USER")
        if name:
            return pwd.getpwnam(name).pw_uid
    except (KeyError, OSError):
        pass
    try:
        uids = [int(d) for d in os.listdir("/run/user") if d.isdigit() and int(d) >= 1000]
        if uids:
            return min(uids)
    except OSError:
        pass
    return 1000


def _runtime_dir() -> Path:
    uid = _desktop_uid()
    return Path(f"/run/user/{uid}")


def status_path() -> Path:
    return _runtime_dir() / "aipc-voice-state.json"


def overlay_sock_path() -> Path:
    return _runtime_dir() / "aipc-overlay.sock"


def _write_status_file(
    state: str,
    detail: str,
    *,
    source: str,
    priority: int,
    partial: str = "",
) -> None:
    p = status_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        labels = {
            "working": "AIPC · 工具執行中",
            "thinking": "AIPC · 思考中",
            "error": "AIPC · 出錯",
            "speaking": "AIPC · 回答中",
        }
        payload = {
            "state": state,
            "detail": detail,
            "partial": partial or detail,
            "label": labels.get(state, f"AIPC · {state}"),
            "hint": detail,
            "source": source,
            "priority": priority,
            "ts": time.time(),
        }
        p.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _overlay_rpc(cmd: str, **fields: Any) -> bool:
    sock = overlay_sock_path()
    if not sock.exists():
        return False
    req = {"cmd": cmd, **fields}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.8)
        s.connect(str(sock))
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        # drain one line
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(2048)
            if not chunk:
                break
            buf += chunk
        s.close()
        return True
    except OSError:
        return False


_STATE_LABELS = {
    "working": "AIPC · 工具執行中",
    "thinking": "AIPC · 思考中",
    "error": "AIPC · 出錯",
    "speaking": "AIPC · 回答中",
}


def progress(
    detail: str,
    *,
    state: str = "working",
    source: str = "agent",
    priority: int = 90,
) -> None:
    """Show tool/agent progress on the Siri-like overlay (and status file)."""
    detail = (detail or "處理中…")[:120]
    label = _STATE_LABELS.get(state, f"AIPC · {state}")
    # Prefer control socket (immediate); always write status file as fallback.
    ok = _overlay_rpc(
        "set",
        state=state,
        detail=detail,
        partial=detail,
        source=source,
        priority=priority,
        label=label,
    )
    _write_status_file(
        state, detail, source=source, priority=priority, partial=detail
    )
    if not ok:
        print(f"aipc-agent-ux: {state} — {detail} (status-file only)", flush=True)
    else:
        print(f"aipc-agent-ux: {state} — {detail}", flush=True)


def tool_names_from_message(msg: object) -> list[str]:
    """Extract tool call names from a LangChain AIMessage-like object."""
    names: list[str] = []
    tcs = getattr(msg, "tool_calls", None) or []
    for tc in tcs:
        if isinstance(tc, dict):
            n = tc.get("name") or tc.get("id") or ""
        else:
            n = getattr(tc, "name", "") or ""
        if n:
            names.append(str(n))
    # additional_kwargs.tool_calls (OpenAI shape)
    if not names:
        ak = getattr(msg, "additional_kwargs", None) or {}
        for tc in ak.get("tool_calls") or []:
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                n = fn.get("name") or tc.get("name") or ""
                if n:
                    names.append(str(n))
    return names


_TOOL_LABELS = {
    "calendar_lookup": "查日曆",
    "email_lookup": "查郵件",
    "web_search": "搜尋網路",
    "search_searxng": "搜尋",
    "search_tavily": "搜尋",
    "files_read": "讀檔案",
    "usage_lookup": "查用量",
    "lookup_usage": "查用量",
}


def humanize_tools(names: list[str]) -> str:
    if not names:
        return "執行工具…"
    parts = [_TOOL_LABELS.get(n, n) for n in names[:4]]
    return "工具：" + "、".join(parts)


_TARGET_LABELS = {
    "respond": "闲聊回答",
    "daily_assistant": "日曆/搜尋/用量",
    "hermes": "Hermes 工具",
    "coder": "编码助手",
    "clarify": "需要确认",
    "job_status": "任务进度",
    "screen_see": "看桌面",
}


def humanize_plan(
    target: str,
    mode: str = "short",
    *,
    agent: str = "",
    source: str = "",
) -> str:
    """One-line plan for overlay after fast front-door dispatch."""
    label = _TARGET_LABELS.get(target or "respond", target or "处理")
    if agent:
        label = f"{label}/{agent}"
    if mode == "long":
        return f"计划：{label} · 后台长任务"
    if source == "rules":
        return f"计划：{label}（快速）"
    if source in ("oneshot", "oneshot:task-default-hermes") or (
        isinstance(source, str) and source.startswith("oneshot")
    ):
        return f"计划：{label}（一次说完）"
    return f"计划：{label}"


def announce_plan(
    target: str,
    mode: str = "short",
    *,
    agent: str = "",
    source: str = "",
) -> None:
    progress(
        humanize_plan(target, mode, agent=agent, source=source),
        state="thinking" if mode != "long" else "working",
        source="plan",
        priority=95,
    )
