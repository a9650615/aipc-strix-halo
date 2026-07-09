"""CodexBar tray — official CLI data + Wayland-safe popover."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from codexbar_gui.icon_updater import make_simple_pixmap, paint_usage_pixmap
from codexbar_gui.popover import UsagePopover
from codexbar_gui.server_launcher import kill_server, start_server
from codexbar_gui.upstream import fetch_usage_views, find_codexbar_binary
from codexbar_gui.usage_panel import summary_from_views

logger = logging.getLogger("codexbar_gui.tray_app")

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
REFRESH_INTERVAL_MS = 60_000


def _is_wayland() -> bool:
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    plat = QApplication.instance()
    if plat is not None:
        name = plat.platformName().lower()
        return "wayland" in name
    return False


class CodexBarApp:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        refresh_interval_ms: int = REFRESH_INTERVAL_MS,
    ) -> None:
        self._host = host
        self._port = port
        self._refresh_interval_ms = refresh_interval_ms
        self._app: Optional[QApplication] = None
        self._tray: Optional[QSystemTrayIcon] = None
        self._popover: Optional[UsagePopover] = None
        self._refresh_timer: Optional[QTimer] = None
        self._server_proc: Optional[subprocess.Popen] = None
        self._current_used: Optional[float] = None

    def run(self) -> int:
        # Prefer xcb only if user forces it; default keep session platform.
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("CodexBar")
        self._app.setQuitOnLastWindowClosed(False)

        binary = find_codexbar_binary()
        logger.info(
            "CodexBar GUI host=%s:%d refresh=%ds binary=%s wayland=%s platform=%s",
            self._host,
            self._port,
            self._refresh_interval_ms // 1000,
            binary or "MISSING",
            _is_wayland(),
            self._app.platformName(),
        )
        if not binary:
            QMessageBox.critical(
                None,
                "CodexBar",
                "Official codexbar CLI not found.\n"
                "Install Linux binary from:\n"
                "https://github.com/steipete/CodexBar/releases\n\n"
                "This app is a GUI shell only.",
            )
            return 1

        self._popover = UsagePopover(self._host, self._port)
        self._init_tray()
        self._start_server()
        self._refresh_data()
        self._start_refresh_timer()

        if self._tray is None or not self._tray.isSystemTrayAvailable():
            QMessageBox.warning(
                None,
                "CodexBar",
                "No system tray available.\nOpening usage window instead.",
            )
            self._popover.show_at_cursor()
        else:
            self._tray.show()
            # Show once so user sees data without fighting Wayland menu grab.
            QTimer.singleShot(300, self._open_popover)

        try:
            return self._app.exec()
        finally:
            self._cleanup()

    def _init_tray(self) -> None:
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(QIcon(make_simple_pixmap("C", 24, "#4a90d9")))
        self._tray.setToolTip("CodexBar — click for usage")
        # Do NOT use setContextMenu(QMenu) with QWidgetActions on Wayland —
        # it fails with "Failed to create grabbing popup".
        # Left/right/double-click all open the Wayland-safe popover.
        self._tray.activated.connect(self._on_activated)

    def _open_popover(self) -> None:
        if self._popover is None:
            return
        try:
            self._popover.show_at_cursor()
        except Exception:
            logger.exception("failed to show popover")

    def _start_server(self) -> bool:
        try:
            ok, proc = start_server(self._host, self._port)
            if ok:
                self._server_proc = proc
                logger.info("official codexbar serve ready on :%s", self._port)
                return True
            logger.info(
                "no official serve on :%s — using `codexbar usage` CLI for data "
                "(this is fine; port 8000 is unused by design, default is 8080)",
                self._port,
            )
            return True
        except Exception as exc:
            logger.error("server start: %s", exc)
            return True  # CLI still works

    def _refresh_data(self) -> None:
        try:
            views = fetch_usage_views(self._host, self._port, prefer_cli=True)
            used, tip = summary_from_views(views)
            self._current_used = used
            err = not views or all(not v.ok for v in views)
            self._set_icon(percent=used, error=err)
            if self._tray:
                self._tray.setToolTip(tip + "\n(click tray icon)")
        except Exception:
            logger.warning("refresh failed", exc_info=True)
            self._set_icon(error=True)

    def _start_refresh_timer(self) -> None:
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(self._refresh_interval_ms)

    def _set_icon(self, percent: Optional[float] = None, error: bool = False) -> None:
        if not self._tray:
            return
        pct = percent if percent is not None else self._current_used
        self._tray.setIcon(QIcon(paint_usage_pixmap(percent=pct, error=error, size=24)))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger = left click; Context = right click on some platforms;
        # DoubleClick / MiddleClick also open the popover.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.MiddleClick,
            QSystemTrayIcon.ActivationReason.Context,
        ):
            self._open_popover()

    def _cleanup(self) -> None:
        if self._refresh_timer:
            self._refresh_timer.stop()
        kill_server()
        if self._popover:
            self._popover.hide()
        if self._tray:
            self._tray.hide()


def main(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    refresh_interval_ms: int = REFRESH_INTERVAL_MS,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    return CodexBarApp(host, port, refresh_interval_ms).run()


if __name__ == "__main__":
    sys.exit(main())
