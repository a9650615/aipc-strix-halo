"""Tray presentation compatibility layer.

Keeps ``UsagePopover`` as the single UI. Host strategy:

- **window** (default): free top-level via ``show_at_tray``. Always opens.
  Docks to the panel screen top-right when SNI click coords are bogus (0,0).
- **sni_menu** (opt-in): embed in SNI ``setContextMenu`` for host-placed
  right-click. Left-click still uses the window path — pure Wayland
  ``QMenu.popup`` without a transient parent fails to map
  (``Failed to create grabbing popup``).

Env: ``CODEXBAR_TRAY_SHELL=window|sni_menu`` (default ``window``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Protocol

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
    QWidgetAction,
)

logger = logging.getLogger("codexbar_gui.shell_adapter")


class PopoverSurface(Protocol):
    def apply_tray_views(self, views: list) -> None: ...
    def set_web_url(self, url: Optional[str]) -> None: ...
    def prepare_open(self) -> None: ...
    def show_at_tray(self, tray=None, click_pos=None) -> None: ...
    def hide(self) -> None: ...
    def isVisible(self) -> bool: ...  # noqa: N802
    def close_host(self) -> None: ...


def choose_shell_mode() -> str:
    forced = os.environ.get("CODEXBAR_TRAY_SHELL", "").strip().lower()
    if forced in {"sni_menu", "window"}:
        return forced
    # Default window: always maps on Plasma Wayland. sni_menu full-UI popup
    # fails without a transient parent (see open() docs).
    return "window"


def reliable_click_pos(
    click_pos: Optional[QPoint] = None,
    tray: Optional[QSystemTrayIcon] = None,
) -> QPoint:
    """Return a dock-safe global point (never trust SNI (0,0) as mid-desktop)."""
    try:
        if tray is not None:
            g = tray.geometry()
            if g.isValid() and 2 < g.width() < 400 and 2 < g.height() < 200:
                return QPoint(g.right(), g.bottom())
    except Exception:
        pass

    pt = click_pos
    if pt is None:
        try:
            pt = QCursor.pos()
        except Exception:
            pt = QPoint(0, 0)

    screen = QGuiApplication.screenAt(pt) if pt is not None else None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return pt if pt is not None else QPoint(80, 48)

    avail = screen.availableGeometry()
    # Bogus Activate coords are often (0,0) or the virtual-desktop origin
    if pt.x() <= 2 and pt.y() <= 2:
        return QPoint(avail.right() - 16, avail.top() + 12)

    band = 72
    near = (
        pt.y() <= avail.top() + band
        or pt.y() >= avail.bottom() - band
        or pt.x() <= avail.left() + band
        or pt.x() >= avail.right() - band
    )
    if near:
        return pt
    # Mid-screen: dock under typical top-right tray cluster on that screen
    return QPoint(avail.right() - 16, avail.top() + 12)


class WindowTrayShell:
    """Free top-level host — reliable open on Wayland + X11."""

    mode = "window"

    def __init__(self, tray: Optional[QSystemTrayIcon], popover: Any) -> None:
        self._tray = tray
        self._popover = popover
        if hasattr(popover, "set_host_closer"):
            popover.set_host_closer(self.close)

    def attach(self) -> None:
        logger.info("tray shell=window (free top-level show_at_tray)")

    def open(self, click_pos: Optional[QPoint] = None) -> None:
        # Always (re)show — isVisible()-based toggle gets stuck on xcb/Wayland.
        pos = reliable_click_pos(click_pos, self._tray)
        logger.info("window shell open at %s (raw_click=%s)", pos, click_pos)
        self._popover.show_at_tray(self._tray, click_pos=pos)

    def close(self) -> None:
        self._popover.hide()

    def is_open(self) -> bool:
        return bool(self._popover.isVisible())

    def on_views(self, views: list) -> None:
        self._popover.apply_tray_views(views)

    def set_web_url(self, url: Optional[str]) -> None:
        self._popover.set_web_url(url)


class SniMenuTrayShell:
    """Optional SNI menu host.

    Right-click: Plasma may show ``setContextMenu`` under the icon.
    Left-click: **always** uses the free window path (QMenu.popup is broken
    on pure Wayland without a transient parent).
    """

    mode = "sni_menu"

    def __init__(self, tray: QSystemTrayIcon, popover: Any) -> None:
        self._tray = tray
        self._popover = popover
        self._window = WindowTrayShell(tray, popover)
        # Lightweight context menu for right-click discovery only — not the full UI
        # (full QWidgetAction popup fails to map on Wayland).
        self._menu = QMenu()
        self._menu.setTitle("CodexBar")
        act_open = self._menu.addAction("Open CodexBar")
        act_open.triggered.connect(lambda: self._window.open())
        act_quit = self._menu.addAction("Quit")
        act_quit.triggered.connect(lambda: self._request_quit())
        if hasattr(popover, "set_host_closer"):
            popover.set_host_closer(self.close)

    def _request_quit(self) -> None:
        try:
            self._popover.quit_requested.emit()
        except Exception:
            logger.exception("quit from sni menu")

    def attach(self) -> None:
        self._tray.setContextMenu(self._menu)
        logger.info(
            "tray shell=sni_menu (right-click menu; left-click → free window)"
        )

    def open(self, click_pos: Optional[QPoint] = None) -> None:
        # Never QMenu.popup for the full UI on Wayland — use free window.
        self._window.open(click_pos=click_pos)

    def close(self) -> None:
        self._menu.close()
        self._window.close()

    def is_open(self) -> bool:
        return self._window.is_open()

    def on_views(self, views: list) -> None:
        self._window.on_views(views)

    def set_web_url(self, url: Optional[str]) -> None:
        self._window.set_web_url(url)


def build_tray_shell(
    tray: Optional[QSystemTrayIcon],
    popover: Any,
    *,
    mode: Optional[str] = None,
) -> Any:
    m = (mode or choose_shell_mode()).lower()
    if m == "sni_menu" and tray is not None:
        return SniMenuTrayShell(tray, popover)
    return WindowTrayShell(tray, popover)
