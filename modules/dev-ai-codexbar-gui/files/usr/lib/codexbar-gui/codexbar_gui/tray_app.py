"""CodexBar system tray application."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from codexbar_gui.icon_updater import make_simple_pixmap, paint_usage_pixmap
from codexbar_gui.server_launcher import kill_server, start_server
from codexbar_gui.usage_panel import UsagePanel, fetch_usage_data, summary_from_data

logger = logging.getLogger("codexbar_gui.tray_app")

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
REFRESH_INTERVAL_MS = 60_000


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
        self._panel: Optional[UsagePanel] = None
        self._refresh_timer: Optional[QTimer] = None
        self._server_proc: Optional[subprocess.Popen] = None
        self._current_percent: Optional[float] = None

    def run(self) -> int:
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("CodexBar")
        self._app.setQuitOnLastWindowClosed(False)

        logger.info(
            "Starting CodexBar http://%s:%d refresh=%ds",
            self._host,
            self._port,
            self._refresh_interval_ms // 1000,
        )

        self._init_tray()
        self._start_server()
        self._refresh_data()
        self._start_refresh_timer()

        if self._tray is None or not self._tray.isSystemTrayAvailable():
            logger.warning("System tray unavailable")
            QMessageBox.warning(
                None,
                "CodexBar",
                "No system tray available.\n"
                "On GNOME install AppIndicator / StatusNotifier support.",
            )
        else:
            self._tray.show()

        logger.info("CodexBar is running")
        try:
            return self._app.exec()
        finally:
            self._cleanup()

    def _init_tray(self) -> None:
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(QIcon(make_simple_pixmap("C", 24, "#4a90d9")))
        self._tray.setToolTip("CodexBar — AI usage")
        self._panel = UsagePanel(self._host, self._port)
        self._tray.setContextMenu(self._panel)
        self._tray.activated.connect(self._on_tray_activated)

    def _start_server(self) -> bool:
        try:
            ok, proc = start_server(self._host, self._port)
            if ok:
                self._server_proc = proc
                return True
            self._update_icon(error=True)
            QTimer.singleShot(400, self._show_server_error)
            return False
        except Exception as exc:
            logger.error("server start: %s", exc)
            self._update_icon(error=True)
            return False

    def _show_server_error(self) -> None:
        QMessageBox.warning(
            None,
            "CodexBar",
            "Failed to start usage server.\n"
            f"Try: aipc usage serve --port {self._port}\n"
            f"or: aipc-usage serve --port {self._port}",
        )

    def _refresh_data(self) -> None:
        try:
            data = fetch_usage_data(self._host, self._port)
            if not data:
                self._update_icon(error=True)
                if self._tray:
                    self._tray.setToolTip("CodexBar — no data / server down")
                return
            max_pct, tip = summary_from_data(data)
            self._current_percent = max_pct
            self._update_icon(percent=max_pct, error=False)
            if self._tray:
                self._tray.setToolTip(tip)
        except Exception:
            logger.warning("refresh failed", exc_info=True)
            self._update_icon(error=True)

    def _start_refresh_timer(self) -> None:
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(self._refresh_interval_ms)

    def _update_icon(
        self,
        percent: Optional[float] = None,
        error: bool = False,
    ) -> None:
        if self._tray is None:
            return
        pct = percent if percent is not None else self._current_percent
        pm = paint_usage_pixmap(percent=pct, error=error, size=24)
        self._tray.setIcon(QIcon(pm))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger = left click on many desktops; DoubleClick kept for compatibility.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self._panel:
                self._panel.popup(QCursor.pos())

    def _cleanup(self) -> None:
        logger.info("Cleaning up CodexBar")
        if self._refresh_timer:
            self._refresh_timer.stop()
        # Only stop the server we spawned (kill_server tracks that).
        kill_server()
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
    return CodexBarApp(
        host=host, port=port, refresh_interval_ms=refresh_interval_ms
    ).run()


if __name__ == "__main__":
    sys.exit(main())
