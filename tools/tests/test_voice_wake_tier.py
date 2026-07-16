"""Unit tests for anti-ghost wake tier / arm decision (shipped code).

Imports the real module under modules/voice-wake — not a re-implementation.
"""
from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WAKE_PATH = ROOT / "modules/voice-wake/files/usr/lib/aipc-voice/aipc_voice_wake.py"


def _load_wake():
    spec = importlib.util.spec_from_file_location("aipc_voice_wake_under_test", WAKE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Ensure module path for optional ux imports does not break load
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wake():
    return _load_wake()


PHRASES = ["嘿助理", "hey assistant", "你好助理", "小廢物"]


def test_fuzzy_particle_is_not_clear_phrase_hit(wake):
    assert wake.phrase_hit("我。", PHRASES) is None
    assert wake.phrase_hit("我", PHRASES) is None
    assert wake.phrase_hit("嘿", PHRASES) is None
    tier, phrase = wake.classify_wake_text("我。", PHRASES)
    assert tier == "fuzzy"
    assert phrase is None


def test_clear_wake_phrase_still_hits(wake):
    assert wake.phrase_hit("嘿助理", PHRASES) == "嘿助理"
    assert wake.phrase_hit("hey assistant", PHRASES) == "hey assistant"
    tier, phrase = wake.classify_wake_text("嘿助理", PHRASES)
    assert tier == "clear"
    assert phrase == "嘿助理"


def test_decide_arm_fuzzy_low_score_no_arm(wake):
    d = wake.decide_wake_arm("fuzzy", 15, allow_fuzzy_promote=True, promote_score=62)
    assert d["arm"] is False
    assert d["arm_reason"] == "ghost_suppressed"
    assert d["intentional"] is False


def test_decide_arm_fuzzy_high_score_promotes(wake):
    d = wake.decide_wake_arm("fuzzy", 80, allow_fuzzy_promote=True, promote_score=62)
    assert d["arm"] is True
    assert d["arm_reason"] == "fuzzy_promoted"
    assert d["intentional"] is True


def test_decide_arm_fuzzy_promote_disabled(wake):
    d = wake.decide_wake_arm("fuzzy", 99, allow_fuzzy_promote=False, promote_score=62)
    assert d["arm"] is False
    assert d["arm_reason"] in ("ghost_suppressed", "candidate")


def test_decide_arm_clear_and_ptt(wake):
    d = wake.decide_wake_arm("clear", 0, phrase="嘿助理")
    assert d["arm"] is True and d["arm_reason"] == "clear_wake"
    d2 = wake.decide_wake_arm("none", 0, ptt=True)
    assert d2["arm"] is True and d2["arm_reason"] == "ptt"


def test_score_wake_pcm_promotes_speech_not_click(wake):
    frame = wake.SAMPLE_RATE * wake.FRAME_MS // 1000
    silence = struct.pack("<h", 0) * frame
    speech = struct.pack("<h", 9000) * frame
    click = speech + silence * 30
    spoken = silence * 2 + speech * 22 + silence * 2  # ~660ms of speech
    s_click = wake.score_wake_pcm(click, noise_floor=400.0, thr=2000.0)
    s_spoken = wake.score_wake_pcm(spoken, noise_floor=400.0, thr=2000.0)
    assert s_spoken >= wake.PROMOTE_SCORE or s_spoken > s_click
    assert s_click < wake.PROMOTE_SCORE


def test_junk_capture_reprompt_once_when_intentional(wake):
    assert wake.junk_capture_action(intentional=True, reprompt_used=0) == "reprompt"
    assert wake.junk_capture_action(intentional=True, reprompt_used=1) == "idle"
    assert wake.junk_capture_action(intentional=False, reprompt_used=0) == "idle"


def test_next_mode_after_empty_capture_wiring(wake):
    """Live loop must leave command on idle; stay command on reprompt.

    Regression: idle only cleared UX and left mode=command → start-timeout loop.
    """
    assert wake.next_mode_after_empty_capture("reprompt") == "command"
    assert wake.next_mode_after_empty_capture("idle") == "listen"
    # Full intentional path: first junk → reprompt/command; second → idle/listen
    a1 = wake.junk_capture_action(intentional=True, reprompt_used=0)
    assert a1 == "reprompt"
    assert wake.next_mode_after_empty_capture(a1) == "command"
    a2 = wake.junk_capture_action(intentional=True, reprompt_used=1)
    assert a2 == "idle"
    assert wake.next_mode_after_empty_capture(a2) == "listen"
    # Non-intentional (follow-up noise): immediate listen
    a0 = wake.junk_capture_action(intentional=False, reprompt_used=0)
    assert wake.next_mode_after_empty_capture(a0) == "listen"


def test_miss_backoff_escalates_not_fixed_1_5s(wake):
    """Thrash protection: consecutive misses grow cool-off (not ~1.5s loop)."""
    b1 = wake.miss_backoff_seconds(1, base=6.0, cap=90.0)
    b3 = wake.miss_backoff_seconds(3, base=6.0, cap=90.0)
    b5 = wake.miss_backoff_seconds(5, base=6.0, cap=90.0)
    b99 = wake.miss_backoff_seconds(99, base=6.0, cap=90.0)
    assert b1 == 6.0
    assert b3 == 12.0
    assert b5 == 48.0
    assert b99 == 90.0
    assert b3 > b1 and b5 > b3
    # Must not be the old fixed ~1.5s miss cooldown
    assert b1 >= 4.0


def test_effective_wake_policy_dump(wake):
    pol = wake.effective_wake_policy()
    assert "allow_fuzzy_promote" in pol
    assert "miss_backoff_base" in pol
    assert pol["max_reprompts"] >= 1
    # Prefer miss: promote off by default in shipped policy/defaults
    assert pol["allow_fuzzy_promote"] is False


def test_end_to_end_decision_matrix(wake):
    """Drive classify → score → decide like the live wake path."""
    # ambient STT particle + weak pcm → no arm
    tier, ph = wake.classify_wake_text("我。", PHRASES)
    weak = struct.pack("<h", 100) * (wake.SAMPLE_RATE // 2)
    sc = wake.score_wake_pcm(weak, noise_floor=500.0, thr=2200.0)
    d = wake.decide_wake_arm(tier, sc, phrase=ph, allow_fuzzy_promote=True)
    assert d["arm"] is False

    # clear text arms even with modest score
    tier2, ph2 = wake.classify_wake_text("嘿助理", PHRASES)
    d2 = wake.decide_wake_arm(tier2, 10, phrase=ph2)
    assert d2["arm"] is True and d2["intentional"] is True


def test_live_loop_wires_policy_helpers_not_orphan_defs():
    """Structural: run_phrase_loop body must call shipped policy helpers."""
    src = WAKE_PATH.read_text(encoding="utf-8")
    assert "_MANGLED_WAKE" not in src
    # Call sites (not only defs)
    assert "classify_wake_text(text, phrases)" in src
    assert "decide_wake_arm(" in src
    assert "miss_backoff_seconds(miss_streak)" in src
    assert "junk_capture_action(" in src
    assert "next_mode_after_empty_capture(action)" in src
    # FOLLOWUP_DIRECT default must prefer off (matches policy.env)
    assert 'AIPC_WAKE_FOLLOWUP_DIRECT", "0"' in src or (
        'AIPC_WAKE_FOLLOWUP_DIRECT", "0"' in src.replace("'", '"')
    )
