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
            "done": "AIPC · 已回答",
            "listening": "AIPC · 監聽中",
            "followup": "AIPC · 可接話",
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
            chunk = s.recv(8192)
            if not chunk:
                break
            buf += chunk
            if len(buf) > 262144:
                break
        s.close()
        return True
    except OSError:
        return False


def overlay_alive() -> bool:
    """True when the glass HUD is up (prefer over native notify-send)."""
    if not overlay_sock_path().exists():
        return False
    return _overlay_rpc("ping")


_STATE_LABELS = {
    "working": "AIPC · 工具執行中",
    "thinking": "AIPC · 思考中",
    "error": "AIPC · 出錯",
    "speaking": "AIPC · 回答中",
    "done": "AIPC · 已回答",
    "listening": "AIPC · 監聽中",
    "followup": "AIPC · 可接話",
}

# Generation + throttle: background ticks must not flash the HUD every 2s,
# and a late followup clear must not clobber a newer Hermes run.
import re
import threading

_UX_LOCK = threading.Lock()
_UX_GEN = 0
_LAST_PUSH: dict[str, Any] = {
    "t": 0.0,
    "state": "",
    "core": "",  # detail without trailing （Ns）
    "source": "",
    "gen": 0,
}

_ELAPSED_TAIL = re.compile(
    r"(?:[（(]\s*(?:已\s*)?\d+\s*s\s*[）)]|\s*[·•]\s*\d+\s*s)\s*$",
    re.IGNORECASE,
)


def _core_detail(detail: str) -> str:
    """Strip timer tails so '工具執行中… · 10s' ≈ '工具執行中… · 12s' for throttle."""
    s = (detail or "").strip()
    s = _ELAPSED_TAIL.sub("", s)
    return s.strip()


def _bump_gen() -> int:
    global _UX_GEN
    with _UX_LOCK:
        _UX_GEN += 1
        return _UX_GEN


def current_gen() -> int:
    with _UX_LOCK:
        return _UX_GEN


def progress(
    detail: str,
    *,
    state: str = "working",
    source: str = "agent",
    priority: int = 90,
    ttl_s: float | None = None,
    force: bool = False,
    gen: int | None = None,
) -> None:
    """Show tool/agent progress on the glass HUD (and status file).

    Background ticks (working/thinking) are throttled so the top card does not
    flash every few seconds. Terminal states (done/error/speaking) always push.
    """
    # Final answers need room for long Hermes replies; progress ticks stay short.
    if state in ("speaking", "done", "error"):
        lim = int(os.environ.get("AIPC_UX_DETAIL_CHARS", "2500"))
    else:
        lim = int(os.environ.get("AIPC_UX_PROGRESS_CHARS", "160"))
    try:
        lim = max(40, lim)
    except (TypeError, ValueError):
        lim = 2500 if state in ("speaking", "done", "error") else 160
    detail = (detail or "處理中…")[:lim]
    label = _STATE_LABELS.get(state, f"AIPC · {state}")
    core = _core_detail(detail)
    now = time.time()

    try:
        min_gap = float(os.environ.get("AIPC_UX_PROGRESS_MIN_GAP_S", "3.5"))
    except ValueError:
        min_gap = 3.5
    # Elapsed-only ticks can refresh slower (stable phase text)
    try:
        elapsed_gap = float(os.environ.get("AIPC_UX_ELAPSED_GAP_S", "8.0"))
    except ValueError:
        elapsed_gap = 8.0

    terminal = state in ("done", "error", "speaking", "followup", "listening")
    global _UX_GEN
    with _UX_LOCK:
        last = _LAST_PUSH
        # Stale delayed clear loses to newer generation (even if force=True)
        if gen is not None and gen < int(last.get("gen") or 0):
            return
        same_phase = (
            state == last.get("state")
            and core == last.get("core")
            and source == last.get("source")
        )
        same_state = state == last.get("state") and source == last.get("source")
        dt = now - float(last.get("t") or 0)
        if not force and not terminal:
            if same_phase and dt < elapsed_gap:
                return  # only the （Ns） changed — skip flash
            if same_state and core == last.get("core") and dt < min_gap:
                return
            if same_state and dt < min_gap and last.get("core"):
                if float(last.get("t") or 0) > 0:
                    low = core.lower()
                    if not any(
                        k in low
                        for k in ("錯誤", "错误", "error", "超時", "超时", "fail")
                    ):
                        return
        # New terminal work or forced: bump gen so old clear threads die
        if terminal and state in ("done", "error", "speaking"):
            _UX_GEN += 1
            use_gen = _UX_GEN
        elif gen is not None:
            use_gen = gen
            if gen > int(last.get("gen") or 0):
                _UX_GEN = gen
        else:
            if state in ("working", "thinking") and source != last.get("source"):
                _UX_GEN += 1
            use_gen = _UX_GEN
        _LAST_PUSH.clear()
        _LAST_PUSH.update(
            {
                "t": now,
                "state": state,
                "core": core,
                "source": source,
                "gen": use_gen,
                "detail": detail,
            }
        )

    fields: dict[str, Any] = {
        "state": state,
        "detail": detail,
        "partial": detail,
        "source": source,
        "priority": priority,
        "label": label,
        "gen": use_gen,
    }
    if ttl_s is not None and ttl_s > 0:
        fields["ttl_s"] = float(ttl_s)
        fields["hold_s"] = float(ttl_s)
    ok = _overlay_rpc("set", **fields)
    try:
        p = status_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "state": state,
            "detail": detail,
            "partial": detail,
            "label": label,
            "hint": detail if state in ("working", "thinking") else "",
            "source": source,
            "priority": priority,
            "ts": time.time(),
            "gen": use_gen,
        }
        if ttl_s is not None and ttl_s > 0:
            payload["ttl_s"] = float(ttl_s)
            payload["hold_s"] = float(ttl_s)
        p.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        _write_status_file(
            state, detail, source=source, priority=priority, partial=detail
        )
    tag = "status-file only" if not ok else "ok"
    shown = detail if len(detail) <= 120 else detail[:117] + "…"
    print(f"aipc-agent-ux: {state} — {shown} ({tag})", flush=True)


def finish_answer(detail: str, *, source: str = "agent", hold_s: float = 60.0) -> None:
    """Show final reply as done (not stuck on 回答中). Keep answer readable for feedback.

    hold_s: how long overlay should keep the answer (default 60s). After that we
    go to followup (可接话 / 可说不对) rather than instantly vanishing.
    A generation token ensures a later Hermes run is not wiped by this clear.
    """
    text = (detail or "完成").strip()
    hold = hold_s
    try:
        hold = float(os.environ.get("AIPC_UX_DONE_HOLD_S", str(hold_s)))
    except ValueError:
        pass
    hold = max(12.0, hold)
    # Terminal push bumps gen
    progress(text, state="done", source=source, priority=95, ttl_s=hold, force=True)
    my_gen = current_gen()

    def _clear() -> None:
        try:
            time.sleep(hold)
            # Only clear if nothing newer took the HUD
            if current_gen() != my_gen:
                return
            progress(
                "可说「不对」反馈，或直接说下一句",
                state="followup",
                source=source,
                priority=45,
                ttl_s=30.0,
                force=True,
                gen=my_gen,
            )
        except Exception:
            pass

    threading.Thread(target=_clear, name="aipc-ux-done", daemon=True).start()


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
