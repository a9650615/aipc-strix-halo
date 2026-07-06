"""Thin client for screen-control grants over aipc-agent-gate (phase-4-agent#5.3).

Wraps gate_client.send() -- no RPC logic duplicated here, just the
screen-control-specific action name, scope choice, and the fixed task id
used for the "always" mode (task-scoped grants never expire on their own;
only revoke() ends them). See modules/agent-screen-control/files/usr/lib/
aipc-agent/aipc_agent_screen_control/gate.py for the consumer side: a
grant here only lifts the gate check, it never bypasses the window-class
blacklist at /etc/aipc/agent-gate/screen-blacklist.conf.
"""

from aipc_lib import gate_client as gate_client_mod

ACTION = "screen-control"
ALWAYS_TASK_ID = "screen-control-always"
BLACKLIST_PATH = "/etc/aipc/agent-gate/screen-blacklist.conf"


def grant_session(duration: str, sock_path: str = gate_client_mod.DEFAULT_SOCKET_PATH) -> dict:
    """Grant screen-control for DURATION seconds (session scope, auto-expires)."""
    try:
        duration_seconds = int(duration)
    except ValueError:
        return {"error": f"duration must be an integer number of seconds, got {duration!r}"}
    return gate_client_mod.send(
        {"cmd": "grant", "actions": [ACTION], "scope": "session", "duration_seconds": duration_seconds},
        sock_path=sock_path,
    )


def grant_always(sock_path: str = gate_client_mod.DEFAULT_SOCKET_PATH) -> dict:
    """Grant screen-control with no expiry (task scope, fixed sentinel task id)."""
    return gate_client_mod.send(
        {"cmd": "grant", "actions": [ACTION], "scope": "task", "task_id": ALWAYS_TASK_ID},
        sock_path=sock_path,
    )


def revoke(sock_path: str = gate_client_mod.DEFAULT_SOCKET_PATH) -> dict:
    """Revoke the always-on grant.

    ponytail: only cancels the ALWAYS_TASK_ID grant -- session-scope grants
    auto-expire and aren't tracked by task_id, so there's nothing for a
    bare `--revoke` to target there. To cancel a session grant early, use
    the generic `aipc agent gate revoke --grant-id <id>` with the id from
    the grant response. Upgrade path if that proves too fiddly: have
    grant_session() persist its grant_id to a small state file this
    module reads back.
    """
    return gate_client_mod.send({"cmd": "revoke", "task_id": ALWAYS_TASK_ID}, sock_path=sock_path)
