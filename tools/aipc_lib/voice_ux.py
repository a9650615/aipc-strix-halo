"""Shared voice UX protocol for aipc CLI + runtime helpers.

Contract (stable):
  Status file: $XDG_RUNTIME_DIR/aipc-voice-state.json
  Fields: state, detail, partial, label, hint, ts
  States: listening | wake | recording | thinking | speaking | done |
          no_speech | miss | error | muted

Runtime modules (voice-wake, voice-once, overlay) and the aipc CLI all share
this file + state vocabulary so overlay / notify / portal stay in sync.

This module is the **aipc-side** API. Live daemons also ship
`aipc_voice_ux.py` under /var/lib/aipc-voice/lib (same schema) for when
systemd units cannot import aipc_lib.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- schema (keep in lockstep with modules/.../aipc_voice_ux.py) ---

STATES: dict[str, tuple[str, str, str, str]] = {
    "listening": (
        "AIPC · 監聽中",
        "說喚醒詞「嘿助理」或按控制中心",
        "low",
        "",
    ),
    "wake": (
        "AIPC · 已喚醒",
        "請說指令，說完停一下",
        "normal",
        "嗯",
    ),
    "recording": (
        "AIPC · 正在聽",
        "錄音中… 說完停一下就結束",
        "normal",
        "",
    ),
    "thinking": (
        "AIPC · 思考中",
        "辨識與回答中，請稍候",
        "low",
        "",
    ),
    "speaking": (
        "AIPC · 回答中",
        "{detail}",
        "low",
        "",
    ),
    "done": (
        "AIPC · 待命",
        "說完了。再說喚醒詞可繼續",
        "low",
        "",
    ),
    "no_speech": (
        "AIPC · 沒聽到",
        "沒有清楚語音，請再說一次喚醒詞",
        "normal",
        "",
    ),
    "miss": (
        "AIPC · 未命中",
        "聽到了但不是喚醒詞：{detail}",
        "low",
        "",
    ),
    "error": (
        "AIPC · 出錯",
        "{detail}",
        "critical",
        "",
    ),
    "muted": (
        "AIPC · 已靜音",
        "喚醒已暫停",
        "low",
        "",
    ),
    "detecting": (
        "AIPC · 偵測中",
        "聽到聲音，正在辨識喚醒詞…",
        "low",
        "",
    ),
}

KNOWN_STATES = frozenset(STATES)

_NOTIFY_ID = "aipc-voice-state"
_last_state = ""
_last_ts = 0.0
_last_notify_key = ""
_last_notify_ts = 0.0
# Only these states may raise a native notification bubble.
# Overlay owns the continuous UX; notify is for rare/urgent only.
_NOTIFY_ALLOW = frozenset({"error", "no_speech"})
# When overlay is down, also allow a single "session start" cue.
_NOTIFY_ALLOW_NO_OVERLAY = frozenset({"error", "no_speech", "wake"})


@dataclass(frozen=True)
class VoiceStatus:
    state: str
    detail: str = ""
    partial: str = ""
    label: str = ""
    hint: str = ""
    ts: float = 0.0
    path: str = ""

    @property
    def ok(self) -> bool:
        return self.state not in ("error",)


def status_path() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "aipc-voice-state.json"
    return Path.home() / ".cache/aipc/voice-state.json"


def wake_sock_paths() -> list[Path]:
    uid = os.geteuid()
    xdg = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return [
        Path(xdg) / "aipc-wake.sock",
        Path(f"/tmp/aipc-wake-{uid}.sock"),
        Path("/tmp/aipc-wake-1000.sock"),
    ]


def read_status(path: Path | None = None) -> VoiceStatus:
    p = path or status_path()
    if not p.is_file():
        return VoiceStatus(state="listening", label=STATES["listening"][0], path=str(p))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return VoiceStatus(state="error", detail="status file unreadable", path=str(p))
    return VoiceStatus(
        state=str(data.get("state") or "listening"),
        detail=str(data.get("detail") or ""),
        partial=str(data.get("partial") or ""),
        label=str(data.get("label") or ""),
        hint=str(data.get("hint") or ""),
        ts=float(data.get("ts") or 0.0),
        path=str(p),
    )


def write_status(
    state: str,
    detail: str = "",
    *,
    partial: str = "",
    path: Path | None = None,
) -> Path:
    """Write status JSON for overlay + aipc voice status."""
    if state not in KNOWN_STATES:
        # allow extension but tag label
        title, body_t = f"AIPC · {state}", "{detail}"
    else:
        title, body_t, _u, _c = STATES[state]
    p = path or status_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = body_t.format(detail=detail or "…") if "{detail}" in body_t else body_t
    payload: dict[str, Any] = {
        "state": state,
        "detail": detail,
        "partial": partial or detail,
        "ts": time.time(),
        "label": title,
        "hint": body,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def _notify_id_path() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(xdg) if xdg else Path.home() / ".cache/aipc"
    return base / "aipc-voice-notify.id"


def _overlay_running() -> bool:
    try:
        st, ok = overlay_status()
        return ok or st == "active"
    except Exception:
        return False


def _notify_mode() -> str:
    """auto | 0/off | 1/on/force

    auto (default): suppress native bubbles when overlay is active; otherwise
    only rare states (wake/error/no_speech). Status file always updates.
    """
    raw = (os.environ.get("AIPC_VOICE_UX_NOTIFY") or "auto").strip().lower()
    if raw in ("0", "off", "false", "no"):
        return "off"
    if raw in ("1", "on", "true", "yes", "force", "always"):
        return "on"
    return "auto"


def _should_native_notify(state: str) -> bool:
    mode = _notify_mode()
    if mode == "off":
        return False
    if mode == "on":
        # Still never spam listening/recording/thinking/done.
        return state in (_NOTIFY_ALLOW | _NOTIFY_ALLOW_NO_OVERLAY | {"error"})
    # auto
    if _overlay_running():
        return state in _NOTIFY_ALLOW
    return state in _NOTIFY_ALLOW_NO_OVERLAY


def _notify(title: str, body: str, urgency: str, timeout_ms: int) -> None:
    if not shutil.which("notify-send"):
        return
    id_path = _notify_id_path()
    replace_id = None
    try:
        if id_path.is_file():
            replace_id = int(id_path.read_text().strip() or "0") or None
    except (OSError, ValueError):
        replace_id = None

    cmd = [
        "notify-send",
        "--app-name=AIPC Voice",
        f"--urgency={urgency}",
        f"--expire-time={timeout_ms}",
        "--transient",
        f"--hint=string:x-canonical-private-synchronous:{_NOTIFY_ID}",
        f"--hint=string:desktop-entry:aipc-voice",
        "--print-id",
    ]
    if replace_id:
        cmd.append(f"--replace-id={replace_id}")
    cmd.extend([title, body])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        new_id = (proc.stdout or "").strip().splitlines()
        if new_id and new_id[0].isdigit():
            try:
                id_path.parent.mkdir(parents=True, exist_ok=True)
                id_path.write_text(new_id[0] + "\n")
            except OSError:
                pass
    except (OSError, subprocess.TimeoutExpired):
        pass


def _cue(text: str) -> None:
    if not text or os.environ.get("AIPC_VOICE_UX_CUE", "1") == "0":
        return
    # No spoken cue when overlay owns UX (avoids double noise with notify history).
    if _notify_mode() == "auto" and _overlay_running():
        return
    bin_ = "espeak-ng" if shutil.which("espeak-ng") else ("espeak" if shutil.which("espeak") else None)
    if not bin_:
        return
    try:
        subprocess.Popen(
            [bin_, "-v", "zh", "-s", "180", "-a", "40", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def announce(
    state: str,
    detail: str = "",
    *,
    notify: bool | None = None,
    cue: bool = True,
    force: bool = False,
    timeout_ms: int | None = None,
    partial: str = "",
) -> VoiceStatus:
    """Publish UX state for overlay (+ rare native notify).

    Status file always updates (overlay reads it). Native desktop notifications
    are suppressed by default when overlay is running, and never fire for
    high-frequency states (listening/recording/thinking/done).
    """
    global _last_state, _last_ts, _last_notify_key, _last_notify_ts
    now = time.monotonic()
    if not force and state == _last_state and (now - _last_ts) < 0.8:
        return read_status()
    _last_state = state
    _last_ts = now

    title, body_t, urgency, cue_text = STATES.get(
        state, (f"AIPC · {state}", "{detail}", "normal", "")
    )
    body = body_t.format(detail=detail or "…") if "{detail}" in body_t else body_t
    write_status(state, detail, partial=partial or detail)
    print(f"aipc-voice-ux: {state} — {body}", flush=True)

    # Media duck + denoise chain for active voice sessions
    try:
        from aipc_lib import voice_audio as voice_audio_mod

        voice_audio_mod.on_voice_state(state)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-voice-ux: audio hook fail: {exc}", flush=True)

    # notify=False → never; notify=True/None → still filtered (anti-spam).
    if notify is False:
        do_notify = False
    else:
        do_notify = _should_native_notify(state)
    if do_notify:
        nkey = f"{state}:{detail[:40]}"
        # Hard debounce even with force=True (wake+recording pairs used force).
        if nkey == _last_notify_key and (now - _last_notify_ts) < 4.0:
            do_notify = False
        elif state == _last_notify_key.split(":", 1)[0] and (now - _last_notify_ts) < 2.0:
            do_notify = False
    if do_notify:
        _last_notify_key = f"{state}:{detail[:40]}"
        _last_notify_ts = now
        if timeout_ms is None:
            timeout_ms = {
                "wake": 2500,
                "no_speech": 3500,
                "error": 6000,
            }.get(state, 3000)
        _notify(title, body, urgency if state == "error" else "low", timeout_ms)

    if cue and state in ("wake", "error", "no_speech"):
        _cue(cue_text)
    return read_status()


def request_ptt(timeout: float = 0.5) -> tuple[bool, str]:
    """Ask wake service to start command capture (single-mic path)."""
    for sp in wake_sock_paths():
        if not sp.exists():
            continue
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(str(sp))
            s.sendall(b"ptt\n")
            s.close()
            return True, str(sp)
        except OSError as exc:
            last = f"{sp}: {exc}"
            continue
    return False, "wake socket not available (is aipc-voice-wake running as user?)"


def user_unit_active(name: str, runner=subprocess.run) -> str:
    proc = runner(
        ["systemctl", "--user", "is-active", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or "").strip() or "inactive"


def overlay_status(runner=subprocess.run) -> tuple[str, bool]:
    st = user_unit_active("aipc-voice-overlay.service", runner=runner)
    return st, st == "active"


def overlay_control(action: str, runner=subprocess.run) -> tuple[int, str]:
    """action: start | stop | restart | status"""
    if action == "status":
        st, ok = overlay_status(runner=runner)
        return (0 if ok else 1), st
    proc = runner(
        ["systemctl", "--user", action, "aipc-voice-overlay.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    msg = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode, msg or action


def format_ux_line(st: VoiceStatus | None = None) -> str:
    st = st or read_status()
    age = ""
    if st.ts:
        age = f" age={max(0.0, time.time() - st.ts):.0f}s"
    detail = st.detail or st.partial or "-"
    if len(detail) > 60:
        detail = detail[:57] + "…"
    return f"{st.state}  {st.label or ''}  {detail}{age}  ({st.path})"


def collect_ux_probes(
    *,
    unit_active=None,
    user_active=user_unit_active,
) -> list[tuple[str, str, bool]]:
    """Probes for aipc voice status: (name, detail, ok)."""
    rows: list[tuple[str, str, bool]] = []
    st = read_status()
    rows.append(("ux-state", format_ux_line(st), st.state != "error"))

    ov, ov_ok = overlay_status(runner=subprocess.run)
    rows.append(("overlay", f"user-unit={ov}", ov_ok or ov == "inactive"))

    # system wake unit
    if unit_active is None:
        from aipc_lib.voice_ops import unit_is_active

        unit_active = unit_is_active
    wake = unit_active("aipc-voice-wake.service")
    rows.append(("wake", f"unit={wake}", wake == "active"))

    sock_ok = any(p.exists() for p in wake_sock_paths())
    rows.append(("wake-sock", "up" if sock_ok else "missing", sock_ok))
    return rows
