"""Unit tests for aipc_voice_session state machine (shipped module)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "modules/voice-wake/files/usr/lib/aipc-voice"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from aipc_voice_session import (  # noqa: E402
    Session,
    SessionState,
    mic_mode,
    on_empty_capture,
    on_ptt,
    on_wake_decision,
    ui_allowed,
)


def test_mic_mode_mapping():
    assert mic_mode(SessionState.IDLE) == "listen"
    assert mic_mode(SessionState.WAKE_BUFFER) == "wake_buf"
    assert mic_mode(SessionState.CAPTURING) == "command"
    assert mic_mode(SessionState.REPROMPT_CAPTURING) == "command"
    assert mic_mode(SessionState.FOLLOWUP_ARMED) == "listen"
    assert mic_mode(SessionState.FOLLOWUP_CAPTURING) == "command"


def test_ui_not_allowed_on_idle_or_followup_armed():
    assert ui_allowed(SessionState.IDLE) is False
    assert ui_allowed(SessionState.FOLLOWUP_ARMED) is False
    assert ui_allowed(SessionState.CAPTURING) is True


def test_on_wake_decision_arm_and_miss():
    s = Session()
    armed = on_wake_decision(
        s, {"arm": True, "intentional": True, "arm_reason": "clear_wake"}
    )
    assert armed.state is SessionState.CAPTURING
    assert armed.intentional is True
    assert armed.miss_streak == 0

    miss = on_wake_decision(
        s, {"arm": False, "intentional": False, "arm_reason": "ghost_suppressed"}
    )
    assert miss.state is SessionState.IDLE
    assert miss.miss_streak == 1


def test_on_empty_capture_reprompt_then_idle():
    s = on_ptt(Session())
    assert s.intentional is True
    s2, a1 = on_empty_capture(s)
    assert a1 == "reprompt"
    assert s2.state is SessionState.REPROMPT_CAPTURING
    assert s2.reprompt_used == 1
    s3, a2 = on_empty_capture(s2)
    assert a2 == "idle"
    assert s3.state is SessionState.IDLE
    assert s3.intentional is False
