"""Multi-monitor dock screen selection for the tray popover."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_tray_icon_rect_rejects_empty_sni() -> None:
    _app()
    from PySide6.QtCore import QRect
    from codexbar_gui.popover import UsagePopover

    tray = MagicMock()
    tray.geometry.return_value = QRect(0, 0, 0, 0)
    assert UsagePopover._tray_icon_rect(tray) is None

    tray.geometry.return_value = QRect(3900, 12, 22, 22)
    rect = UsagePopover._tray_icon_rect(tray)
    assert rect is not None
    assert rect.x() == 3900


def test_resolve_dock_screen_prefers_tray_then_click() -> None:
    _app()
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QGuiApplication
    from codexbar_gui.popover import UsagePopover

    primary = QGuiApplication.primaryScreen()
    assert primary is not None

    # No tray / click → primary (offscreen usually has one virtual screen)
    assert UsagePopover._resolve_dock_screen(None, click_pos=None) is primary

    tray = MagicMock()
    tray.geometry.return_value = QRect(0, 0, 0, 0)
    click = QPoint(primary.geometry().center())
    # Empty tray geometry → click path
    assert UsagePopover._resolve_dock_screen(tray, click_pos=click) is primary


def test_stable_dock_pos_uses_screen_available_geometry() -> None:
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    from codexbar_gui.popover import UsagePopover

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    avail = screen.availableGeometry()
    full = screen.geometry()

    # Click near top-right (typical tray cluster)
    click = QPoint(avail.right() - 16, avail.top() + 12)
    x, y = UsagePopover._stable_dock_pos(None, 420, 400, click_pos=click)
    # Must land inside the chosen screen's full rect
    assert full.left() <= x <= full.right()
    assert full.top() <= y <= full.bottom()
    # Right-aligned under the click
    assert x >= avail.right() - 420 - 40
    assert y <= click.y() + 40
    assert isinstance(QPoint(x, y), QPoint)


def test_stable_dock_pos_under_valid_tray_rect() -> None:
    _app()
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    from codexbar_gui.popover import UsagePopover

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    avail = screen.availableGeometry()
    # Fake tray icon near top-right of available area
    icon = QRect(avail.right() - 40, avail.top() + 4, 24, 24)
    tray = MagicMock()
    tray.geometry.return_value = icon

    w, h = 420, 400
    x, y = UsagePopover._stable_dock_pos(tray, w, h, click_pos=None)
    # Docked on same screen under top panel
    assert avail.left() <= x <= avail.right() - 100
    assert y <= avail.top() + 20
    assert y >= avail.top()


def test_dock_mid_screen_click_falls_back_to_top_right() -> None:
    """Bogus SNI cursor mid-screen must not center the popover."""
    _app()
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QGuiApplication
    from codexbar_gui.popover import UsagePopover

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    avail = screen.availableGeometry()
    click = avail.center()
    tray = MagicMock()
    tray.geometry.return_value = QRect(0, 0, 0, 0)

    x, y = UsagePopover._stable_dock_pos(None, 420, 400, click_pos=click)
    assert x >= avail.right() - 420 - 24
    assert y <= avail.top() + 16


def test_clamp_popover_rect_keeps_fully_on_screen() -> None:
    from PySide6.QtCore import QRect
    from codexbar_gui.popover import clamp_popover_rect

    avail = QRect(0, 0, 1920, 1080)
    # prefer_pin: keep top, shrink height (do not float to center)
    x, y, w, h = clamp_popover_rect(1500, 40, 420, 2000, avail, prefer_pin=True)
    assert y == 40 + 0 or y == 44 or y == 40  # margin may not move top when already ok
    assert y <= 50
    assert y + h <= avail.bottom() + 1
    assert h < 2000

    # Secondary monitor offset
    avail2 = QRect(3840, 0, 1920, 1080)
    x2, y2, w2, h2 = clamp_popover_rect(5000, 50, 420, 2000, avail2)
    assert avail2.left() <= x2
    assert x2 + w2 <= avail2.right() + 1
    assert y2 + h2 <= avail2.bottom() + 1
    assert h2 <= avail2.height() - 8
    # pin stays near top under tray
    assert y2 == 50


def test_dock_follows_click_when_tray_geometry_empty() -> None:
    _app()
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QGuiApplication
    from codexbar_gui.popover import UsagePopover

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    avail = screen.availableGeometry()
    # Simulate click on tray at top-right (empty SNI geometry)
    click = QPoint(avail.right() - 20, avail.top() + 10)
    tray = MagicMock()
    tray.geometry.return_value = QRect(0, 0, 0, 0)

    anchor = UsagePopover._tray_anchor_rect(tray, click_pos=click)
    assert anchor.contains(click) or abs(anchor.center().x() - click.x()) <= 12

    x, y = UsagePopover._stable_dock_pos(tray, 420, 400, click_pos=click)
    # Just below top panel; on the right side near the tray cluster
    assert x + 420 <= avail.right() + 8
    assert y <= avail.top() + 20
    assert y < avail.center().y()
