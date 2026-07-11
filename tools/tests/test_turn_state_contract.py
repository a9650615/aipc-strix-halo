"""Turn-state contract tests (headless, pure).

phase-3-voice-assistant: follow-up ("接话") window must be driven by
turn-completion state, not opened after every answer. Three states:
end (rc=2, farewell, unchanged) / reply (rc=3, assistant expects a reply,
opens a short follow-up) / done (rc=0, default — answered, no follow-up).
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VOICE_ONCE = REPO / "modules/voice-pipecat/files/usr/bin/aipc-voice-once"


def _load_voice_once():
    loader = SourceFileLoader("aipc_voice_once", str(VOICE_ONCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


def test_turn_rc_end_session_wins():
    m = _load_voice_once()
    assert m._turn_rc(end_session=True, expect_reply=True) == 2
    assert m._turn_rc(end_session=True, expect_reply=False) == 2


def test_turn_rc_expect_reply_opens_followup():
    m = _load_voice_once()
    assert m._turn_rc(end_session=False, expect_reply=True) == 3


def test_turn_rc_plain_answer_no_followup():
    m = _load_voice_once()
    assert m._turn_rc(end_session=False, expect_reply=False) == 0
