from __future__ import annotations

from aipc_assistant.backends import local as local_backend
from aipc_assistant.backends.online import load_online_backend
from aipc_assistant.registry import bootstrap_builtin, is_pack_enabled, list_packs
from aipc_assistant.slots import actions as actions_slot
from aipc_assistant.slots import context as context_slot
from aipc_assistant.slots import control as control_slot
from aipc_assistant.slots import mode as mode_slot
from aipc_assistant.types import Action, TurnRequest, TurnResponse


def run_turn(req: TurnRequest) -> TurnResponse:
    bootstrap_builtin()
    text = (req.text or "").strip()
    online = load_online_backend()
    mode = mode_slot.get_mode()
    if req.prefer in ("local", "online"):
        mode = req.prefer

    # Control on user text (and later online transcript events).
    decided: list[Action] = []
    if text:
        decided = control_slot.decide(text, role="user")

    action_log = actions_slot.execute(decided, online_backend=online)
    mode = mode_slot.get_mode()  # may have changed

    # If control only changed mode / closed session with no remaining work.
    only_meta = bool(decided) and all(
        a.name in ("mode_local", "mode_online", "session_close", "voice_stop", "none")
        for a in decided
    )
    if only_meta and not _needs_fulfillment(text, decided):
        return TurnResponse(
            text="; ".join(action_log) or "ok",
            mode_used=mode,
            actions=decided,
            backend=None,
        )

    # Strip simple handoff prefixes for fulfillment (v0 heuristic).
    fulfill_text = _strip_handoff_prefix(text) if text else text

    if mode == "online":
        from aipc_assistant.onboarding import friendly_online_error

        if not online.available():
            return TurnResponse(
                text="",
                mode_used=mode,
                actions=decided,
                error=friendly_online_error(online.status()),
                backend="online",
            )
        # First-time: not logged in → clear UX instead of cryptic DOM errors
        try:
            st = online.status()
            logged = st.get("logged_in")
            if logged is False or (
                logged is None
                and hasattr(online, "auth_status")
                and online.auth_status().get("logged_in") is False  # type: ignore[attr-defined]
            ):
                return TurnResponse(
                    text="",
                    mode_used=mode,
                    actions=decided,
                    error=friendly_online_error(st),
                    backend="online",
                )
        except Exception:
            pass
        bundle = context_slot.assemble_bundle(fulfill_text or text)
        try:
            from aipc_assistant.slots.timeouts import apply_timeout_if_needed, new_watch

            watch = new_watch()
            if req.modality == "voice":
                online.turn_voice(context_bundle=bundle)
                # One-shot turn: record watch metadata; long-running daemon is v1.
                # Immediate max/idle check is a no-op at t=0; callers may poll.
                reason = apply_timeout_if_needed(watch, online)
                note = "(online voice session started)"
                if reason:
                    note = f"(online voice ended: {reason})"
                return TurnResponse(
                    text=note,
                    mode_used=mode,
                    actions=decided,
                    backend="online",
                )
            reply = online.inject_and_send(fulfill_text or text, context_bundle=bundle)
            watch.touch()
            return TurnResponse(
                text=reply or "(sent online)",
                mode_used=mode,
                actions=decided,
                backend="online",
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if any(
                k in msg.lower()
                for k in ("login", "登入", "auth", "not installed", "playwright")
            ):
                msg = friendly_online_error({"error": msg})
            return TurnResponse(
                text="",
                mode_used=mode,
                actions=decided,
                error=msg,
                backend="online",
            )

    # local
    if not fulfill_text:
        return TurnResponse(
            text="",
            mode_used=mode,
            actions=decided,
            error="empty text",
            backend="local",
        )
    try:
        reply = local_backend.chat(fulfill_text, session_id=req.session_id)
        return TurnResponse(
            text=reply,
            mode_used=mode,
            actions=decided,
            backend="local",
        )
    except Exception as exc:  # noqa: BLE001
        return TurnResponse(
            text="",
            mode_used=mode,
            actions=decided,
            error=str(exc),
            backend="local",
        )


def _needs_fulfillment(text: str, actions: list[Action]) -> bool:
    if not text.strip():
        return False
    # If user only said an end phrase, actions handle it.
    if actions and len(text.strip()) < 40:
        return False
    return True


def _strip_handoff_prefix(text: str) -> str:
    prefixes = (
        "網上助理",
        "用 ChatGPT",
        "切到語音 ChatGPT",
        "online mode",
        "online assistant",
    )
    t = text.strip()
    lower = t.lower()
    for p in prefixes:
        if lower.startswith(p.lower()):
            return t[len(p) :].strip(" ，,：:")
        if p in t:
            # "用 ChatGPT 解釋 X" → remainder after phrase
            idx = lower.find(p.lower())
            if idx >= 0:
                rem = t[idx + len(p) :].strip(" ，,：:")
                if rem:
                    return rem
    return t


def status_dict() -> dict:
    from aipc_assistant.onboarding import diagnose, is_first_run

    bootstrap_builtin()
    online = load_online_backend()
    packs = [
        {"name": p.name, "slot": p.slot, "enabled": is_pack_enabled(p.name), "desc": p.description}
        for p in list_packs()
    ]
    report = diagnose()
    from aipc_assistant.backends import local as local_backend

    npu_ok, npu_detail = local_backend.npu_reachable()
    return {
        "mode": mode_slot.get_mode(),
        "first_run": is_first_run(),
        "ready_local": report.ready_local,
        "ready_online": report.ready_online,
        "npu_first": True,
        "backend_local": {
            "mode": "auto (NPU resident-small first, agent :4100 fallback)",
            "npu_ok": npu_ok,
            "npu_detail": npu_detail,
            "agent_url": "http://127.0.0.1:4100/chat (optional, runtime local_backend.mode=agent|auto)",
        },
        "backend_online": online.status(),
        "setup_checks": [
            {"id": c.id, "ok": c.ok, "title": c.title, "detail": c.detail}
            for c in report.checks
        ],
        "next_steps": report.next_steps,
        "packs": packs,
        "version": "0.2.0",
    }
