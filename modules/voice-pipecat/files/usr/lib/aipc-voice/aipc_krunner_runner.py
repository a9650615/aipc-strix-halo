#!/usr/bin/env python3
"""KRunner DBus runner: Spotlight-like entry to the AIPC closed-loop assistant.

Install (user session): aipc-krunner-install
Type in KRunner (Alt+Space / Meta+Space): aipc …  or  助理 …
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)

SERVICE = "org.kde.aipc_assistant"
OBJPATH = "/runner"

def _ux(state: str, detail: str = "") -> None:
    """Best-effort shared UX (overlay/status) — never fail the runner."""
    try:
        from aipc_lib.voice_ux import announce
        announce(state, detail, force=True, cue=False)
        return
    except Exception:
        pass
    try:
        import aipc_voice_ux as voice_ux  # type: ignore
        voice_ux.announce(state, detail, force=True, cue=False)
    except Exception:
        pass


IFACE = "org.kde.krunner1"

CHAT_URL = os.environ.get("AIPC_VOICE_CHAT_URL", "http://127.0.0.1:4100/chat")
ONCE = os.environ.get(
    "AIPC_VOICE_ONCE",
    shutil.which("aipc-voice-once") or "/home/birdyo/.local/bin/aipc-voice-once",
)
TRIGGERS = (
    "aipc ",
    "aipc:",
    "助理 ",
    "助手 ",
    "問 ",
    "问 ",
    "ask ",
    "? ",
    "？",
)


def _strip_trigger(query: str) -> str | None:
    q = query.strip()
    if not q:
        return None
    low = q.lower()
    if low in ("aipc", "助理", "助手", "ask"):
        return ""
    for t in TRIGGERS:
        if low.startswith(t.lower()) or q.startswith(t):
            return q[len(t) :].strip()
    # Long free-text only with explicit leading ?
    if q.startswith("?") or q.startswith("？"):
        return q[1:].strip()
    return None


def _chat(text: str, timeout: float = 45.0) -> tuple[str, str]:
    """Return (full_text, spoken_summary). KRunner owns TTS when it speaks."""
    payload = json.dumps(
        {"text": text, "session_id": "krunner", "source": "krunner"}
    ).encode()
    req = urllib.request.Request(
        CHAT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    full = str(data.get("text") or "").strip()
    spoken = str(data.get("spoken_summary") or "").strip()
    return full, spoken


def _overlay_present(title: str, body: str, *, state: str = "done") -> bool:
    """Prefer glass HUD over native notify-send for full answers."""
    import json
    import socket
    import time
    from pathlib import Path

    xdg = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    detail = (body or "")[:2500]
    payload = {
        "state": state,
        "detail": detail,
        "partial": detail,
        "label": (title or "AIPC · 已回答")[:40],
        "hint": "可滾動閱讀 · 說「不对」可反饋" if state == "done" else "",
        "source": "krunner",
        "priority": 95,
        "ttl_s": 90.0 if state == "done" else 12.0,
        "ts": time.time(),
    }
    try:
        sp = Path(xdg) / "aipc-voice-state.json"
        sp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass
    sock_path = Path(xdg) / "aipc-overlay.sock"
    if not sock_path.exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.6)
        s.connect(str(sock_path))
        req = {"cmd": "set", **payload}
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        s.recv(2048)
        s.close()
        return True
    except OSError:
        return False


def _notify(title: str, body: str) -> None:
    """HUD first; native notify-send only if overlay is unavailable."""
    if _overlay_present(title, body):
        return
    mode = (os.environ.get("AIPC_DESKTOP_NOTIFY") or "auto").strip().lower()
    if mode in ("0", "off", "false", "no", "never"):
        return
    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "-a", "AIPC", title, (body or "")[:400]],
            check=False,
            timeout=5,
        )


def _portal_open() -> None:
    aipc = shutil.which("aipc")
    if aipc:
        subprocess.Popen([aipc, "portal", "open"], start_new_session=True)
        return
    subprocess.Popen(
        ["xdg-open", "http://127.0.0.1:7080/"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _voice_once() -> None:
    cmd = ONCE if Path(ONCE).is_file() else (shutil.which("aipc-voice-once") or ONCE)
    subprocess.Popen(
        [cmd, "--seconds", "5"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _speak(text: str) -> None:
    """Best-effort TTS; never touches volume."""
    try:
        for p in (
            Path("/var/lib/aipc-voice/lib"),
            Path("/usr/lib/aipc-voice"),
        ):
            if (p / "aipc_voice_tts.py").is_file():
                import sys

                sys.path.insert(0, str(p))
                import aipc_voice_tts  # type: ignore

                aipc_voice_tts.speak(text)
                return
    except Exception:
        pass


class Runner(dbus.service.Object):
    def __init__(self) -> None:
        bus_name = dbus.service.BusName(SERVICE, dbus.SessionBus())
        super().__init__(bus_name, OBJPATH)

    @dbus.service.method(IFACE, in_signature="s", out_signature="a(sssida{sv})")
    def Match(self, query: str):  # noqa: N802
        rest = _strip_trigger(query)
        if rest is None:
            return []
        matches = []
        if rest:
            preview = rest if len(rest) < 80 else rest[:77] + "…"
            matches.append(
                (
                    f"ask:{rest}",
                    f"Ask AIPC: {preview}",
                    "dialog-messages",
                    100,
                    1.0,
                    {
                        "subtext": "Local assistant (resident-small) · Enter to ask",
                        "category": "AIPC Assistant",
                    },
                )
            )
        matches.append(
            (
                "voice",
                "AIPC: listen (push-to-talk 5s)",
                "audio-input-microphone",
                100,
                0.9 if rest else 1.0,
                {"subtext": "Same as F20 / voice wake", "category": "AIPC Assistant"},
            )
        )
        matches.append(
            (
                "portal",
                "AIPC: open management dashboard",
                "dashboard-show",
                100,
                0.85 if rest else 0.95,
                {"subtext": "http://127.0.0.1:7080/", "category": "AIPC Assistant"},
            )
        )
        if not rest:
            matches.append(
                (
                    "help",
                    "AIPC: type “aipc <question>” or “助理 问题”",
                    "help-about",
                    50,
                    0.5,
                    {
                        "subtext": "Spotlight-style local assistant",
                        "category": "AIPC Assistant",
                    },
                )
            )
        return matches

    @dbus.service.method(IFACE, out_signature="a(sss)")
    def Actions(self):  # noqa: N802
        return [
            ("speak", "Speak answer", "audio-volume-high"),
            ("copy", "Copy answer", "edit-copy"),
        ]

    @dbus.service.method(IFACE, in_signature="s")
    def SetActivationToken(self, token: str):  # noqa: N802
        return

    @dbus.service.method(IFACE)
    def Teardown(self):  # noqa: N802
        return

    @dbus.service.method(IFACE, in_signature="ss")
    def Run(self, match_id: str, action_id: str):  # noqa: N802
        if match_id == "voice":
            _voice_once()
            return
        if match_id == "portal":
            _portal_open()
            return
        if match_id == "help":
            _notify("AIPC", "Type: aipc <question>  or  助理 问题")
            return
        if match_id.startswith("ask:"):
            question = match_id[4:]
            # Same local intents as aipc-voice-once (open dashboard, etc.).
            try:
                from aipc_lib.portal import (  # type: ignore
                    ensure_and_open_portal,
                    matches_open_portal_intent,
                )

                if matches_open_portal_intent(question):
                    ok, msg = ensure_and_open_portal()
                    _notify("AIPC", msg)
                    if ok and os.environ.get("AIPC_KRUNNER_SPEAK", "1") == "1":
                        GLib.idle_add(lambda m=msg: (_speak(m), False)[1])
                    return
            except Exception:
                # tools package optional at runtime
                low = question.lower()
                if "dashboard" in low or "portal" in low or "面板" in question:
                    _portal_open()
                    _notify("AIPC", "Opening dashboard")
                    return
            try:
                answer, spoken = _chat(question)
            except Exception as exc:  # noqa: BLE001
                _notify("AIPC error", str(exc)[:300])
                return
            if not answer:
                _notify("AIPC", "(empty reply)")
                return
            # HUD/notify: full result; TTS: spoken_summary only (single owner=krunner)
            _notify("AIPC", answer)
            speech = spoken or answer
            if action_id == "speak" or os.environ.get("AIPC_KRUNNER_SPEAK", "1") == "1":
                GLib.idle_add(lambda s=speech: (_speak(s), False)[1])
            if action_id == "copy" and shutil.which("wl-copy"):
                subprocess.run(["wl-copy", answer], check=False)
            elif action_id == "copy" and shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=answer.encode(),
                    check=False,
                )


def main() -> None:
    Runner()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
