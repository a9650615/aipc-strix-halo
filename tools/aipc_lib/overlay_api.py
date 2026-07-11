"""AIPC assistant overlay control API (for voice + future widgets).

Transport: Unix domain socket at $XDG_RUNTIME_DIR/aipc-overlay.sock
Protocol: one JSON object per line (request → response).

Widgets (voice, hermes HUD, agent tray, …) SHOULD prefer this API over
poking the status file alone when they need show/hide/raise. Status still
lives in aipc-voice-state.json so file watchers keep working.

Commands:
  ping | help | get | show | hide | raise
  set   {state, detail?, partial?, label?, source?, priority?}
  clear {source?}   — hide; if source set, only when it owns current state

Version: 1
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any

API_VERSION = 1
DEFAULT_PRIORITY = 50
VOICE_PRIORITY = 100  # voice-wake / voice-once default

KNOWN_CMDS = frozenset(
    {"ping", "help", "get", "show", "hide", "raise", "set", "clear"}
)


def overlay_sock_paths() -> list[Path]:
    uid = os.geteuid()
    xdg = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return [
        Path(xdg) / "aipc-overlay.sock",
        Path(f"/tmp/aipc-overlay-{uid}.sock"),
        Path("/tmp/aipc-overlay-1000.sock"),
    ]


def default_sock_path() -> Path:
    return overlay_sock_paths()[0]


def parse_request_line(line: str) -> dict[str, Any]:
    """Parse one request line into a dict. Raises ValueError on bad input."""
    raw = (line or "").strip()
    if not raw:
        raise ValueError("empty request")
    # Allow bare words for shell convenience: ping / show / hide
    if raw[0] not in "{[":
        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        if cmd not in KNOWN_CMDS:
            raise ValueError(f"unknown cmd {cmd!r}")
        req: dict[str, Any] = {"cmd": cmd}
        if len(parts) > 1 and cmd == "set":
            # set thinking hello world
            bits = parts[1].split(None, 1)
            req["state"] = bits[0]
            if len(bits) > 1:
                req["detail"] = bits[1]
        elif len(parts) > 1 and cmd == "clear":
            req["source"] = parts[1].strip()
        return req
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object")
    cmd = str(data.get("cmd") or "").lower()
    if cmd not in KNOWN_CMDS:
        raise ValueError(f"unknown cmd {cmd!r}")
    data["cmd"] = cmd
    return data


def handle_request(
    req: dict[str, Any],
    *,
    current: dict[str, Any] | None = None,
    visible: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pure request handler.

    Returns (response, actions) where actions are side-effect descriptors:
      {"op": "show"|"hide"|"raise"|"set_status", ...}
    """
    current = dict(current or {})
    cmd = str(req.get("cmd") or "").lower()
    actions: list[dict[str, Any]] = []

    if cmd == "ping":
        return (
            {
                "ok": True,
                "cmd": "ping",
                "version": API_VERSION,
                "visible": bool(visible),
                "state": current.get("state") or "listening",
                "source": current.get("source") or "",
            },
            [],
        )

    if cmd == "help":
        return (
            {
                "ok": True,
                "cmd": "help",
                "version": API_VERSION,
                "commands": sorted(KNOWN_CMDS),
                "sock": str(default_sock_path()),
                "status_file": "aipc-voice-state.json under XDG_RUNTIME_DIR",
            },
            [],
        )

    if cmd == "get":
        return (
            {
                "ok": True,
                "cmd": "get",
                "version": API_VERSION,
                "visible": bool(visible),
                "status": current,
            },
            [],
        )

    if cmd == "show":
        actions.append({"op": "show"})
        return (
            {
                "ok": True,
                "cmd": "show",
                "version": API_VERSION,
                "visible": True,
            },
            actions,
        )

    if cmd == "hide":
        actions.append({"op": "hide"})
        return (
            {
                "ok": True,
                "cmd": "hide",
                "version": API_VERSION,
                "visible": False,
            },
            actions,
        )

    if cmd == "raise":
        actions.append({"op": "raise"})
        return (
            {
                "ok": True,
                "cmd": "raise",
                "version": API_VERSION,
                "visible": bool(visible),
            },
            actions,
        )

    if cmd == "set":
        state = str(req.get("state") or "").strip()
        if not state:
            return {"ok": False, "cmd": "set", "error": "state required"}, []
        source = str(req.get("source") or "widget").strip() or "widget"
        try:
            priority = int(req.get("priority", DEFAULT_PRIORITY))
        except (TypeError, ValueError):
            priority = DEFAULT_PRIORITY
        # Preempt only if equal-or-higher priority (voice default 100).
        cur_pri = int(current.get("priority") or 0)
        cur_src = str(current.get("source") or "")
        if cur_src and cur_src != source and priority < cur_pri:
            age = time.time() - float(current.get("ts") or 0.0)
            if age < 8.0:
                return (
                    {
                        "ok": False,
                        "cmd": "set",
                        "error": "preempted",
                        "holder": cur_src,
                        "holder_priority": cur_pri,
                    },
                    [],
                )
        detail = str(req.get("detail") or "")
        partial = str(req.get("partial") or detail)
        label = str(req.get("label") or "")
        status = {
            "state": state,
            "detail": detail,
            "partial": partial,
            "label": label,
            "source": source,
            "priority": priority,
            "ts": time.time(),
            "hint": str(req.get("hint") or ""),
        }
        actions.append({"op": "set_status", "status": status})
        actions.append({"op": "show"})
        return (
            {
                "ok": True,
                "cmd": "set",
                "version": API_VERSION,
                "visible": True,
                "status": status,
            },
            actions,
        )

    if cmd == "clear":
        source = str(req.get("source") or "").strip()
        force = bool(req.get("force"))
        cur_src = str(current.get("source") or "")
        if source and cur_src and source != cur_src and not force:
            return (
                {
                    "ok": False,
                    "cmd": "clear",
                    "error": "not_owner",
                    "holder": cur_src,
                },
                [],
            )
        # Return to listening / hidden
        status = {
            "state": "listening",
            "detail": "",
            "partial": "",
            "label": "",
            "source": source or cur_src or "clear",
            "priority": 0,
            "ts": time.time(),
            "hint": "",
        }
        actions.append({"op": "set_status", "status": status})
        actions.append({"op": "hide"})
        return (
            {
                "ok": True,
                "cmd": "clear",
                "version": API_VERSION,
                "visible": False,
                "status": status,
            },
            actions,
        )

    return {"ok": False, "error": f"unknown cmd {cmd!r}"}, []


def rpc(
    cmd: str,
    *,
    timeout: float = 1.5,
    sock_path: Path | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Send one command to the overlay control socket. Raises OSError if down."""
    req = {"cmd": cmd, **fields}
    path = sock_path or default_sock_path()
    last_err: Exception | None = None
    paths = [path] if sock_path else overlay_sock_paths()
    for sp in paths:
        if not sp.exists():
            continue
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(str(sp))
            payload = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
            s.sendall(payload)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            s.close()
            line = buf.decode("utf-8", errors="replace").strip().splitlines()
            if not line:
                return {"ok": False, "error": "empty response"}
            return json.loads(line[0])
        except (OSError, json.JSONDecodeError) as exc:
            last_err = exc
            continue
    raise OSError(str(last_err or "aipc-overlay.sock not available"))


def set_status(
    state: str,
    detail: str = "",
    *,
    source: str = "widget",
    priority: int = DEFAULT_PRIORITY,
    partial: str = "",
    label: str = "",
    timeout: float = 1.5,
) -> dict[str, Any]:
    """Convenience: set overlay state via RPC (widgets should use this)."""
    return rpc(
        "set",
        state=state,
        detail=detail,
        partial=partial or detail,
        label=label,
        source=source,
        priority=priority,
        timeout=timeout,
    )


def show(*, timeout: float = 1.5) -> dict[str, Any]:
    return rpc("show", timeout=timeout)


def hide(*, timeout: float = 1.5) -> dict[str, Any]:
    return rpc("hide", timeout=timeout)


def raise_panel(*, timeout: float = 1.5) -> dict[str, Any]:
    return rpc("raise", timeout=timeout)


def ping(*, timeout: float = 1.0) -> dict[str, Any]:
    return rpc("ping", timeout=timeout)
