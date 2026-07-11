#!/usr/bin/env python3
"""Voice UX runtime — shared contract with tools/aipc_lib/voice_ux.py.

When aipc_lib is importable (aipc CLI env), re-export that implementation so
CLI and daemons never drift. Otherwise use the local fallback below (systemd
units that only have /var/lib/aipc-voice/lib on sys.path).
"""
from __future__ import annotations

try:
    from aipc_lib.voice_ux import (  # noqa: F401
        STATES,
        KNOWN_STATES,
        VoiceStatus,
        announce,
        read_status,
        write_status,
        status_path,
        request_ptt,
        format_ux_line,
        collect_ux_probes,
        overlay_status,
        overlay_control,
        wake_sock_paths,
    )

    _USING_AIPC_LIB = True
except Exception:  # noqa: BLE001
    _USING_AIPC_LIB = False

if not _USING_AIPC_LIB:


    import json
    import os
    import shutil
    import subprocess
    import time
    from pathlib import Path

    # state_id -> (title, body template, urgency, espeak short cue or "")
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
            "AIPC · 已回答",
            "{detail}",
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
    }

    _NOTIFY_ID = "aipc-voice-state"
    _last_state = ""
    _last_ts = 0.0


    def _status_path() -> Path:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            return Path(xdg) / "aipc-voice-state.json"
        home = os.environ.get("HOME", "/tmp")
        return Path(home) / ".cache/aipc/voice-state.json"


    def write_status(state: str, detail: str = "", *, partial: str = "") -> None:
        """Write status for overlay + status CLI.

        partial: optional live transcript / reply snippet for Siri-like panel.
        """
        path = _status_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            title, body_t, _u, _c = STATES.get(state, (state, "{detail}", "normal", ""))
            payload = {
                "state": state,
                "detail": detail,
                "partial": partial or detail,
                "ts": time.time(),
                "label": title,
                "hint": body_t.format(detail=detail or "…") if "{detail}" in body_t else body_t,
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass


    def _notify(title: str, body: str, urgency: str, timeout_ms: int) -> None:
        if not shutil.which("notify-send"):
            return
        # Replace previous AIPC state bubble when DE supports it
        cmd = [
            "notify-send",
            f"--app-name=AIPC Voice",
            f"--urgency={urgency}",
            f"--expire-time={timeout_ms}",
            f"--hint=string:x-canonical-private-synchronous:{_NOTIFY_ID}",
            f"--hint=string:desktop-entry:aipc-voice-once",
            title,
            body,
        ]
        env = os.environ.copy()
        try:
            subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            pass


    def _cue(text: str) -> None:
        """Very short spoken cue (non-blocking). Skip if empty or TTS busy policy."""
        if not text or os.environ.get("AIPC_VOICE_UX_CUE", "1") == "0":
            return
        if not shutil.which("espeak-ng") and not shutil.which("espeak"):
            return
        bin_ = "espeak-ng" if shutil.which("espeak-ng") else "espeak"
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
        notify: bool = True,
        cue: bool = True,
        force: bool = False,
        timeout_ms: int | None = None,
    ) -> None:
        """Publish UX state. Debounces identical state within 0.8s unless force."""
        global _last_state, _last_ts
        now = time.monotonic()
        if not force and state == _last_state and (now - _last_ts) < 0.8:
            return
        _last_state = state
        _last_ts = now

        title, body_t, urgency, cue_text = STATES.get(
            state, (f"AIPC · {state}", "{detail}", "normal", "")
        )
        body = body_t.format(detail=detail or "…")
        if detail and "{detail}" not in body_t and state in ("thinking", "recording"):
            body = f"{body}\n{detail}"

        write_status(state, detail, partial=detail)
        print(f"aipc-voice-ux: {state} — {body}", flush=True)

        if notify and os.environ.get("AIPC_VOICE_UX_NOTIFY", "1") != "0":
            if timeout_ms is None:
                timeout_ms = {
                    "listening": 4000,
                    "wake": 5000,
                    "recording": 8000,
                    "thinking": 15000,
                    "speaking": 8000,
                    "done": 3000,
                    "no_speech": 4000,
                    "miss": 2500,
                    "error": 8000,
                    "muted": 4000,
                }.get(state, 4000)
            _notify(title, body, urgency, timeout_ms)

        if cue:
            _cue(cue_text)
