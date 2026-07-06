"""Shared fail-closed checks for every screen-control action (task 4.7/4.8):
1. the `aipc-agent-gate` permission-gate RPC (design.md D4/D5, task 5.1),
2. the window-class blacklist (design.md D4).

Both input.py and vlm.py call check_action() before doing anything real;
neither implements its own copy of this logic.

UPDATE mid-dispatch: `aipc-agent-gate` (phase-4-agent#5.1) was being built
by a parallel agent in this same tree, and partway through this dispatch it
went live via a hotfix systemd unit (`aipc-agent-gate.service`, see
`modules/agent-gate/` — real `/usr/lib/aipc-agent/aipc_agent_gate/server.py`)
listening on the real `/run/aipc-agent-gate.sock`. Read its server.py
docstring directly and hardware-verified against the live socket: the
contract assumed below is EXACTLY what it implements —
  request:  {"cmd": "check", "action": "screen-control"}
  response: {"allowed": true|false, "grant_id": <str>|null}
Verified live (grant screen-control session 60s -> check_gate() True ->
revoke -> check_gate() False again; grant then revoked immediately after,
no lingering grant left active). `agent-tools-files/tools.py`
(phase-4-agent#4.1, landed first) assumed a DIFFERENT, now-stale shape for
the same then-unbuilt gate: plaintext `"check <action>\\n"` answered with
`b"GRANTED"` — that one needs updating to match the real JSON contract,
this one already does. Fail mode: any connection failure (socket missing,
refused, timeout) or a false/missing "allowed" is treated as "not
granted" — fail closed, never fail open, per CLAUDE.md §10.
"""

import json
import socket

from aipc_agent_screen_control.window import get_active_window_class

GATE_SOCKET = "/run/aipc-agent-gate.sock"
GATE_ACTION = "screen-control"


class GateDenied(PermissionError):
    """The permission gate did not grant screen-control (denied, or the
    gate could not be reached — fail closed either way)."""


class BlacklistedWindow(PermissionError):
    """The active window's class is blacklisted, or its class could not be
    determined at all (also fails closed — unknown is treated as
    blacklisted, not as safe)."""


def _load_blacklist(path: str) -> set[str]:
    try:
        with open(path) as f:
            return {
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            }
    except FileNotFoundError:
        return set()


def check_gate(sock_path: str = GATE_SOCKET, action: str = GATE_ACTION) -> bool:
    """True only if the gate is reachable AND explicitly grants `action`."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(sock_path)
            s.sendall((json.dumps({"cmd": "check", "action": action}) + "\n").encode())
            raw = s.recv(4096)
        reply = json.loads(raw.decode().strip())
        return reply.get("allowed") is True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def is_blacklisted(
    blacklist_path: str = "/etc/aipc/agent-gate/screen-blacklist.conf",
) -> bool:
    """True if the active window is blacklisted OR unknown (fail closed —
    see BlacklistedWindow docstring)."""
    window_class = get_active_window_class()
    if window_class is None:
        return True
    return window_class in _load_blacklist(blacklist_path)


def check_action(
    sock_path: str = GATE_SOCKET,
    action: str = GATE_ACTION,
    blacklist_path: str = "/etc/aipc/agent-gate/screen-blacklist.conf",
) -> None:
    """Raise GateDenied or BlacklistedWindow, or return None (allowed).
    Every screen-control action (input.py, vlm.py) calls this first."""
    if not check_gate(sock_path, action):
        raise GateDenied(f"aipc-agent-gate did not grant '{action}'")
    if is_blacklisted(blacklist_path):
        raise BlacklistedWindow("active window is blacklisted or its class is unknown")
