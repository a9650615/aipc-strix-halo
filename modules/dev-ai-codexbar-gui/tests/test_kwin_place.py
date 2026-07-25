"""KWin placement script contract (no compositor needed).

The script is the only thing that can position the popover on Wayland, so its
generated source is worth pinning: which output it docks on, and what it does
when Plasma gives us no tray rect (multi-monitor fallback).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from codexbar_gui import kwin_place


def _rect(x, y, w, h):
    from PySide6.QtCore import QRect

    return QRect(x, y, w, h)


def test_script_carries_anchor_size_and_title() -> None:
    js = kwin_place.build_script(_rect(2531, 0, 24, 24), 420, 640)
    assert "var anchor = {x: 2531, y: 0, w: 24, h: 24};" in js
    assert "var want = {w: 420, h: 640};" in js
    assert kwin_place.WINDOW_TITLE in js
    assert "var anchorReal = 1;" in js


def test_real_anchor_picks_the_output_under_the_icon() -> None:
    """Multi-monitor: dock on the screen owning the tray, never the primary."""
    js = kwin_place.build_script(_rect(3000, 210, 24, 24), 420, 480)
    assert "workspace.screenAt" in js
    assert "workspace.clientArea(KWin.PlacementArea, out, workspace.currentDesktop)" in js


def test_guessed_anchor_falls_back_to_the_panel_on_the_active_output() -> None:
    js = kwin_place.build_script(_rect(0, 0, 24, 24), 420, 480, anchor_real=False)
    assert "var anchorReal = 0;" in js
    # Panel lookup restricted to one output, largest dock wins
    assert "if (!c.dock) { continue; }" in js
    assert "c.output !== out" in js
    assert "activeOutput" in js


def test_zero_sized_anchor_is_clamped_not_divided_by_zero() -> None:
    js = kwin_place.build_script(_rect(10, 20, 0, 0), 420, 480)
    assert "var anchor = {x: 10, y: 20, w: 1, h: 1};" in js


def test_poll_script_caps_an_untouched_card_that_keeps_focus() -> None:
    """Focus can stay with us forever; the cursor being away then decides."""
    js = kwin_place.build_poll_script(_rect(2531, 0, 24, 24), open_seconds=3)
    assert "var openMs = 3000;" in js
    assert f"var capMs = {int(kwin_place.UNTOUCHED_CAP_S * 1000)};" in js
    assert "} else if (openMs >= capMs) {" in js
    # …but never while the cursor is on the card
    assert "if (!engaged) {" in js


def test_poll_script_closes_only_when_cursor_and_focus_left() -> None:
    js = kwin_place.build_poll_script(_rect(2531, 0, 24, 24))
    # KWin is asked because a Wayland client sees neither of these
    assert "workspace.cursorPos" in js
    assert "workspace.activeWindow" in js
    # Both conditions required before closing
    assert "var engaged = cursorEngaged(pop);" in js
    assert "if (!engaged) {" in js
    assert "if (!oursActive) {" in js
    assert "pop.closeWindow();" in js
    # The tray icon and the gap to the card count as still-engaged
    assert f"var pad = {kwin_place.CURSOR_PAD};" in js
    assert "Math.min(g.x, anchor.x) - pad" in js


def test_resident_script_only_places() -> None:
    js = kwin_place.build_script(_rect(2531, 0, 24, 24), 420, 480)
    assert "workspace.windowAdded.connect" in js
    assert "closeWindow" not in js


def test_disarm_is_safe_without_kwin() -> None:
    kwin_place._armed = None
    kwin_place.disarm()  # must not raise when nothing is loaded
