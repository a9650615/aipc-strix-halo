from __future__ import annotations

from aipc_assistant.slots import mode as mode_slot
from aipc_assistant.types import Action


def execute(actions: list[Action], online_backend=None) -> list[str]:
    """Run allow-listed actions in phase order. Returns log lines."""
    log: list[str] = []
    # Phase order: mode changes, then session, then voice
    order = {
        "mode_online": 10,
        "mode_local": 20,
        "inject_session": 30,
        "inject_delta": 35,
        "feature_enable": 40,
        "feature_run": 45,
        "voice_stop": 50,
        "session_close": 60,
        "none": 99,
    }
    sorted_actions = sorted(actions, key=lambda a: order.get(a.name, 50))
    for act in sorted_actions:
        if act.name == "mode_online":
            mode_slot.set_mode("online")
            log.append("mode=online")
        elif act.name == "mode_local":
            if online_backend is not None:
                try:
                    online_backend.session_close()
                    log.append("online.session_close")
                except Exception as exc:  # noqa: BLE001 — soft
                    log.append(f"online.session_close fail: {exc}")
            mode_slot.set_mode("local")
            log.append("mode=local")
        elif act.name == "session_close":
            if online_backend is not None:
                try:
                    online_backend.session_close()
                    log.append("online.session_close")
                except Exception as exc:  # noqa: BLE001
                    log.append(f"online.session_close fail: {exc}")
            else:
                log.append("session_close (no online backend)")
        elif act.name == "voice_stop":
            if online_backend is not None and hasattr(online_backend, "voice_stop"):
                try:
                    online_backend.voice_stop()
                    log.append("online.voice_stop")
                except Exception as exc:  # noqa: BLE001
                    log.append(f"online.voice_stop fail: {exc}")
            else:
                log.append("voice_stop (noop)")
        elif act.name in ("inject_session", "inject_delta", "feature_enable", "feature_run"):
            log.append(f"{act.name} deferred/noop in v0 skeleton")
        elif act.name == "none":
            continue
        else:
            log.append(f"ignored unknown {act.name}")
    return log
