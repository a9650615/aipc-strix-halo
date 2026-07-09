"""CodexBar tray — data from official ``codexbar`` CLI / serve."""

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
from codexbar_gui.upstream import fetch_usage_views, find_codexbar_binary
from codexbar_gui.usage_panel import UsagePanel, summary_from_views

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
        self._current_used: Optional[float] = None

    def run(self) -> int:
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("CodexBar")
        self._app.setQuitOnLastWindowClosed(False)

        binary = find_codexbar_binary()
        logger.info(
            "CodexBar GUI host=%s:%d refresh=%ds binary=%s",
            self._host,
            self._port,
            self._refresh_interval_ms // 1000,
            binary or "MISSING",
        )
        if not binary:
            logger.warning(
                "Official codexbar binary not found — install Linux CLI "
                "(https://github.com/steipete/CodexBar releases)"
            )

        self._init_tray()
        self._start_server()
        self._refresh_data()
        self._start_refresh_timer()

        if self._tray is None or not self._tray.isSystemTrayAvailable():
            QMessageBox.warning(
                None,
                "CodexBar",
                "No system tray.\nGNOME needs AppIndicator / StatusNotifier.",
            )
        else:
            self._tray.show()

        try:
            return self._app.exec()
        finally:
            self._cleanup()

    def _init_tray(self) -> None:
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(QIcon(make_simple_pixmap("C", 24, "#4a90d9")))
        self._tray.setToolTip("CodexBar")
        self._panel = UsagePanel(self._host, self._port)
        self._tray.setContextMenu(self._panel)
        self._tray.activated.connect(self._on_activated)

    def _start_server(self) -> bool:
        try:
            ok, proc = start_server(self._host, self._port)
            if ok:
                self._server_proc = proc
                return True
            # Port may be occupied by fake aipc-usage — CLI still works.
            if find_codexbar_binary():
                logger.warning(
                    "official serve not on :%s (wrong process or missing); "
                    "GUI uses `codexbar usage` CLI for real data",
                    self._port,
                )
                return True
            self._set_icon(error=True)
            QTimer.singleShot(400, self._show_server_error)
            return False
        except Exception as exc:
            logger.error("server: %s", exc)
            return bool(find_codexbar_binary())

    def _show_server_error(self) -> None:
        QMessageBox.warning(
            None,
            "CodexBar",
            "No official codexbar CLI found.\n"
            "Install: https://github.com/steipete/CodexBar/releases\n\n"
            "Note: default port is 8080 (not 8000).\n"
            "If 8080 is taken by `python -m codexbar_usage`, kill that process.",
        )

    def _refresh_data(self) -> None:
        try:
            # Always CLI when binary present — never trust a random :8080.
            views = fetch_usage_views(self._host, self._port, prefer_cli=True)
            used, tip = summary_from_views(views)
            self._current_used = used
            self._set_icon(percent=used, error=not views or all(not v.ok for v in views))
            if self._tray:
                self._tray.setToolTip(tip)
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
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self._panel:
                self._panel.popup(QCursor.pos())

    def _cleanup(self) -> None:
        if self._refresh_timer:
            self._refresh_timer.stop()
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
    return CodexBarApp(host, port, refresh_interval_ms).run()


if __name__ == "__main__":
    sys.exit(main())
