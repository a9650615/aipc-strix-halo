"""Auto-dismiss must ride the pointer, not activation.

Plasma Wayland grants activation a few hundred ms after the map and then hands it
back to whatever was active before, so an activation-driven popover either closes
on its own or never closes at all.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _popover():
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.popover import UsagePopover

    _ = QApplication.instance() or QApplication([])
    pop = UsagePopover(embedded=False)
    # Far from the (0,0) offscreen cursor so the X11 fallback path is false too
    pop.setGeometry(4000, 4000, 420, 400)
    return pop


def test_watch_timer_started_on_show_and_stopped_on_hide() -> None:
    pop = _popover()
    pop.show()
    pop._start_dismiss_watch()
    assert pop._dismiss_watch is not None and pop._dismiss_watch.isActive()

    pop.hide()
    assert not pop._dismiss_watch.isActive()


def test_untouched_card_closes_after_timeout() -> None:
    pop = _popover()
    pop.show()
    pop._start_dismiss_watch()
    pop._open_grace_until = 0.0

    pop._dismiss_tick()
    assert pop.isVisible()  # still inside UNTOUCHED_TIMEOUT

    pop._shown_at = time.monotonic() - pop.UNTOUCHED_TIMEOUT - 0.1
    pop._dismiss_tick()
    assert not pop.isVisible()


def test_untouched_timeout_fires_even_while_focused() -> None:
    """KWin re-activates the always-on-top card when the thief window closes."""
    pop = _popover()
    pop.show()
    pop._start_dismiss_watch()
    pop._open_grace_until = 0.0
    pop.isActiveWindow = lambda: True  # pretend KWin handed focus back
    pop._shown_at = time.monotonic() - pop.UNTOUCHED_TIMEOUT - 0.1

    pop._dismiss_tick()
    assert not pop.isVisible()


def test_hovered_card_closes_only_after_pointer_leave_grace() -> None:
    pop = _popover()
    pop.show()
    pop._start_dismiss_watch()
    pop._open_grace_until = 0.0
    pop._shown_at = time.monotonic() - 60  # untouched timeout long past

    pop._pointer_seen = True  # user hovered it
    pop._dismiss_tick()  # first tick outside: start the clock
    assert pop.isVisible()
    assert pop._pointer_left_at is not None

    pop._pointer_left_at = time.monotonic() - pop.POINTER_LEAVE_GRACE - 0.1
    pop._dismiss_tick()
    assert not pop.isVisible()


def test_open_grace_and_settings_dialog_block_dismissal() -> None:
    pop = _popover()
    pop.show()
    pop._start_dismiss_watch()
    pop._shown_at = time.monotonic() - 60

    pop._open_grace_until = time.monotonic() + 5
    pop._dismiss_tick()
    assert pop.isVisible()

    pop._open_grace_until = 0.0
    pop._settings_open = True
    pop._dismiss_tick()
    assert pop.isVisible()

    pop._settings_open = False
    pop.hide()


def test_pointer_inside_ignores_stale_cursor_on_wayland(monkeypatch) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QCursor

    from codexbar_gui import popover as pop_mod

    pop = _popover()
    pop.show()
    # Stale QCursor position parked inside the *requested* rect (Wayland freezes it
    # at the last event we saw) must not count as "pointer still on the card".
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(4100, 4100)))
    monkeypatch.setattr(pop_mod, "_is_wayland", lambda: True)
    assert pop._pointer_inside() is False

    monkeypatch.setattr(pop_mod, "_is_wayland", lambda: False)
    assert pop._pointer_inside() is True
    pop.hide()
