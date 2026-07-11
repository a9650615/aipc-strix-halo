"""Overlay widget control API — pure protocol tests (no Qt)."""
from __future__ import annotations

import json

from aipc_lib import overlay_api


def test_parse_bare_and_json() -> None:
    assert overlay_api.parse_request_line("ping")["cmd"] == "ping"
    assert overlay_api.parse_request_line('{"cmd":"show"}')["cmd"] == "show"
    req = overlay_api.parse_request_line("set thinking agent busy")
    assert req["cmd"] == "set"
    assert req["state"] == "thinking"
    assert req["detail"] == "agent busy"


def test_handle_ping_get_show_hide() -> None:
    cur = {"state": "listening", "source": "voice", "priority": 100, "ts": 1.0}
    resp, acts = overlay_api.handle_request({"cmd": "ping"}, current=cur, visible=False)
    assert resp["ok"] is True
    assert resp["version"] == 1
    assert acts == []

    resp, acts = overlay_api.handle_request({"cmd": "show"}, current=cur, visible=False)
    assert resp["ok"] and any(a["op"] == "show" for a in acts)

    resp, acts = overlay_api.handle_request({"cmd": "hide"}, current=cur, visible=True)
    assert resp["ok"] and any(a["op"] == "hide" for a in acts)


def test_set_preempt_by_priority() -> None:
    cur = {
        "state": "speaking",
        "source": "voice",
        "priority": 100,
        "ts": __import__("time").time(),
    }
    # Low priority widget cannot steal while voice holds
    resp, acts = overlay_api.handle_request(
        {"cmd": "set", "state": "thinking", "source": "other", "priority": 10},
        current=cur,
        visible=True,
    )
    assert resp["ok"] is False
    assert resp["error"] == "preempted"
    assert acts == []

    # Equal/higher can update
    resp, acts = overlay_api.handle_request(
        {
            "cmd": "set",
            "state": "thinking",
            "detail": "ok",
            "source": "voice",
            "priority": 100,
        },
        current=cur,
        visible=True,
    )
    assert resp["ok"] is True
    assert any(a["op"] == "set_status" for a in acts)
    st = next(a["status"] for a in acts if a["op"] == "set_status")
    assert st["state"] == "thinking"
    assert st["source"] == "voice"


def test_clear_owner_only() -> None:
    cur = {"state": "thinking", "source": "hermes", "priority": 50, "ts": 1.0}
    resp, acts = overlay_api.handle_request(
        {"cmd": "clear", "source": "other"}, current=cur, visible=True
    )
    assert resp["ok"] is False
    assert resp["error"] == "not_owner"

    resp, acts = overlay_api.handle_request(
        {"cmd": "clear", "source": "hermes"}, current=cur, visible=True
    )
    assert resp["ok"] is True
    assert any(a["op"] == "hide" for a in acts)


def test_request_response_json_roundtrip_shape() -> None:
    resp, _ = overlay_api.handle_request({"cmd": "help"}, current={}, visible=False)
    raw = json.dumps(resp)
    again = json.loads(raw)
    assert "commands" in again
    assert "set" in again["commands"]
