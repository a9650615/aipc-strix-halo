"""Pure-helper + geometry tests for state-driven right/center overlay docking
(headless). Qt runs offscreen; skips cleanly if PySide6 is not installed.

openspec: phase-3 voice overlay — right-dock idle / center-expand activity,
animated slide between the two.
"""

from __future__ import annotations

import importlib.util
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OVL = REPO / "modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py"


def _load():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    loader = SourceFileLoader("aipc_voice_overlay", str(OVL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _mod():
    pytest.importorskip("PySide6")
    return _load()


def _panel(m):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    return m.OverlayPanel()


def test_anchor_for_state_right_states():
    m = _mod()
    for state in ("listening", "wake", "recording", "no_speech", "followup"):
        assert m.OverlayPanel._anchor_for_state(state) == "right", state


def test_anchor_for_state_center_states():
    m = _mod()
    for state in ("thinking", "working", "speaking", "done", "error"):
        assert m.OverlayPanel._anchor_for_state(state) == "center", state


def test_anchor_for_state_unknown_defaults_center():
    m = _mod()
    assert m.OverlayPanel._anchor_for_state("muted") == "center"
    assert m.OverlayPanel._anchor_for_state("") == "center"


def test_effective_anchor_env_override_wins(monkeypatch):
    m = _mod()
    panel = _panel(m)
    monkeypatch.setenv("AIPC_OVERLAY_ANCHOR", "top-right")
    assert panel._effective_anchor("done") == "top-right"
    assert panel._effective_anchor("listening") == "top-right"


def test_effective_anchor_state_driven_by_default(monkeypatch):
    m = _mod()
    panel = _panel(m)
    monkeypatch.delenv("AIPC_OVERLAY_ANCHOR", raising=False)
    monkeypatch.delenv("AIPC_OVERLAY_STATE_DOCK", raising=False)
    assert panel._effective_anchor("listening") == "right"
    assert panel._effective_anchor("done") == "center"


def test_state_dock_disabled_falls_back_to_top_center(monkeypatch):
    m = _mod()
    panel = _panel(m)
    monkeypatch.delenv("AIPC_OVERLAY_ANCHOR", raising=False)
    monkeypatch.setenv("AIPC_OVERLAY_STATE_DOCK", "0")
    assert panel._effective_anchor("listening") == "top-center"
    assert panel._effective_anchor("done") == "top-center"
    # mini should also fall back to the old working/thinking-only rule
    assert panel._mini_for_state("listening") is False
    assert panel._mini_for_state("working") is True


def test_mini_for_state_right_dock_states_are_mini(monkeypatch):
    m = _mod()
    panel = _panel(m)
    monkeypatch.delenv("AIPC_OVERLAY_ANCHOR", raising=False)
    monkeypatch.delenv("AIPC_OVERLAY_STATE_DOCK", raising=False)
    assert panel._mini_for_state("listening") is True
    assert panel._mini_for_state("wake") is True
    assert panel._mini_for_state("working") is True
    assert panel._mini_for_state("thinking") is True
    assert panel._mini_for_state("speaking") is False
    assert panel._mini_for_state("done") is False
    assert panel._mini_for_state("error") is False


def test_compute_geom_right_is_more_rightward_than_center(monkeypatch):
    """listening (right) should place further right (larger x) than done
    (center) on the same screen."""
    m = _mod()
    panel = _panel(m)
    monkeypatch.delenv("AIPC_OVERLAY_ANCHOR", raising=False)
    monkeypatch.delenv("AIPC_OVERLAY_STATE_DOCK", raising=False)

    panel._state = "listening"
    panel._mini = True
    x_right, *_ = panel._compute_geom(body_len=0, long_form=False, mini=True)

    panel._state = "done"
    panel._mini = False
    panel._body_len = 10
    panel._long_form = False
    x_center, *_ = panel._compute_geom(body_len=10, long_form=False, mini=False)

    assert x_right > x_center


def test_place_animates_on_pure_x_move(monkeypatch):
    """A pure horizontal dock move (right -> center, same-ish size) must
    still trigger the geometry animation, not a silent snap."""
    m = _mod()
    panel = _panel(m)
    monkeypatch.delenv("AIPC_OVERLAY_ANCHOR", raising=False)
    monkeypatch.delenv("AIPC_OVERLAY_STATE_DOCK", raising=False)

    calls = []
    panel._animate_geometry = lambda *a, **k: calls.append((a, k))
    panel._compute_geom = lambda **k: (100, 20, 200, 46)  # same size, moved x only
    panel.isVisible = lambda: True
    panel._last_geom = (500, 20, 200, 46)  # far right, same size
    panel._locked_geom = None

    panel._place(force=True, animate=True)

    assert len(calls) == 1
    args = calls[0][0]
    assert args[:2] == (100, 20)  # x, y passed through to _animate_geometry


def test_place_snaps_when_animate_false_despite_x_move():
    """When animate=False (e.g. first paint), a pure x move must NOT animate."""
    m = _mod()
    panel = _panel(m)

    calls = []
    panel._animate_geometry = lambda *a, **k: calls.append((a, k))
    panel._compute_geom = lambda **k: (100, 20, 200, 46)
    panel.isVisible = lambda: True
    panel._last_geom = (500, 20, 200, 46)
    panel._locked_geom = None

    panel._place(force=True, animate=False)

    assert calls == []
