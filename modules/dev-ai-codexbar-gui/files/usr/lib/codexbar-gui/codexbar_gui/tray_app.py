"""Main application class — CodexBar system tray icon.

Orchestrates:
- Server launcher (auto-start the usage HTTP server)
- Usage panel (right-click context menu)
- Icon updater (dynamic SVG icon based on usage)
- Refresh timer (periodic data refresh)
- System tray icon (QSystemTrayIcon)

The app runs as a background daemon in the system tray, with a right-click
menu showing usage data for all configured AI coding providers.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QSystemTrayIcon,
    QMessageBox,
)
from PySide6.QtCore import QTimer, QSize
from PySide6.QtGui import QIcon, QCursor, QPixmap

from codexbar_gui.server_launcher import start_server, kill_server
from codexbar_gui.usage_panel import UsagePanel, fetch_usage_data
from codexbar_gui.icon_updater import generate_svg, svg_to_qicon_pixmap

logger = logging.getLogger("codexbar_gui.tray_app")


DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
REFRESH_INTERVAL_MS = 60000  # 60 seconds
ICON_SIZE = QSize(24, 24)


class CodexBarApp:
    """Main application class for CodexBar system tray.

    Manages the lifecycle of:
    - HTTP server (auto-start, health check)
    - System tray icon (QSystemTrayIcon)
    - Usage data refresh (periodic timer)
    - Icon updates (dynamic SVG based on usage)
    """

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

        # Current usage state for icon updates
        self._current_percent: Optional[float] = None
        self._has_error: bool = False

    def run(self) -> int:
        """Start the application and run the event loop.

        Returns the exit code (0 = normal exit).
        """
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)

        logger.info(
            "Starting CodexBar on http://%s:%d (refresh=%ds)",
            self._host, self._port, self._refresh_interval_ms // 1000,
        )

        # Initialize tray icon
        self._init_tray()

        # Start HTTP server if not running
        self._start_server()

        # Initial data fetch
        self._refresh_data()

        # Start refresh timer
        self._start_refresh_timer()

        if not (self._tray and self._tray.isSystemTrayAvailable()):
            logger.warning("System tray is not available — running without tray icon")

        # Show tray icon
        self._tray.show()

        logger.info("CodexBar is running")

        try:
            return self._app.exec()
        finally:
            self._cleanup()

    def _init_tray(self) -> None:
        """Initialize the system tray icon and context menu."""
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(self._get_default_icon())
        self._tray.setToolTip("CodexBar — AI Usage Tracker")

        # Context menu
        self._panel = UsagePanel(self._host, self._port)
        self._tray.setContextMenu(self._panel)

        # Single connection — avoid double-fire
        self._tray.activated.connect(self._on_tray_activated)

    def _start_server(self) -> bool:
        """Start the HTTP server if it is not already running."""
        try:
            ok, proc = start_server(self._host, self._port)
            if ok:
                self._server_proc = proc
                return True

            # Server failed to start — show error after the event loop begins
            self._has_error = True
            QTimer.singleShot(500, lambda: self._show_server_error())
            return False
        except Exception as e:
            logger.error("Unexpected error starting server: %s", e)
            self._has_error = True
            return False

    def _show_server_error(self) -> None:
        """Show server error dialog (must run inside the event loop)."""
        if self._app:
            QMessageBox.warning(
                None,
                "CodexBar",
                "Failed to start usage server.\n"
                "Please start manually: aipc-usage serve --port " + str(self._port),
            )

    def _refresh_data(self) -> None:
        """Fetch fresh usage data and update icon/menu."""
        try:
            data = fetch_usage_data(self._host, self._port)
            if data:
                logger.debug("Fetched %d provider snapshots", len(data))
                self._update_icon_from_data(data)
            else:
                logger.debug("No usage data returned")
                self._has_error = True
                self._update_icon(error=True)
        except Exception:
            self._has_error = True
            logger.warning("Failed to refresh usage data", exc_info=True)
            self._update_icon(error=True)

    def _start_refresh_timer(self) -> None:
        """Start the periodic refresh timer."""
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(self._refresh_interval_ms)
        logger.debug("Refresh timer started (%dms)", self._refresh_interval_ms)

    def _update_icon_from_data(self, data: list) -> None:
        """Update the tray icon based on usage data."""
        if not data:
            self._has_error = True
            self._update_icon(error=True)
            return

        total = 0
        count = 0
        for item in data:
            snapshot = item.get("snapshot", {})
            primary = snapshot.get("primary") or {}
            used_pct = primary.get("used_percent", 0)
            if used_pct is not None:
                total += max(0, min(100, int(used_pct)))
                count += 1

        if count > 0:
            avg = total / count
            self._current_percent = avg
            self._has_error = False
            self._update_icon(percent=avg)
        else:
            self._has_error = False
            self._update_icon(percent=None)

    def _update_icon(self, percent: Optional[float] = None, error: bool = False) -> None:
        """Generate and set the tray icon SVG."""
        try:
            pct = percent if percent is not None else self._current_percent
            svg = generate_svg(percent=pct, error=error)
            pixmap = svg_to_qicon_pixmap(svg)
            if not pixmap.isNull():
                self._tray.setIcon(QIcon(pixmap))
        except Exception as e:
            logger.warning("Failed to update icon: %s", e)

    def _get_default_icon(self) -> QIcon:
        """Return the default (gray) tray icon."""
        # Use a simple colored square as fallback if SVG fails
        return QIcon(self._make_simple_pixmap("C", "#4a90d9"))

    def _make_simple_pixmap(self, text: str, color: str) -> QPixmap:
        """Create a simple colored square pixmap for the tray icon."""
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtCore import Qt

        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 4, 4)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSizeF(12)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text[:1].upper())
        painter.end()
        return pixmap

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle system tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self._panel:
                self._panel.popup(QCursor.pos())

    def _cleanup(self) -> None:
        """Clean up resources on exit."""
        logger.info("Cleaning up CodexBar")
        if self._refresh_timer:
            self._refresh_timer.stop()
        kill_server()
        if self._tray:
            self._tray.hide()

    def _quit_app(self) -> None:
        """Quit the application."""
        self._cleanup()
        if self._app:
            self._app.quit()


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, refresh_interval_ms: int = REFRESH_INTERVAL_MS) -> int:
    """Entry point for the CodexBar GUI application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = CodexBarApp(host=host, port=port, refresh_interval_ms=refresh_interval_ms)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
