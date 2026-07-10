"""CodexBar tray — official CLI data + Wayland-safe popover + local web UI."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from codexbar_gui.icon_updater import (
    DEFAULT_TRAY_SIZE,
    make_simple_pixmap,
    paint_dual_window_pixmap,
    paint_usage_pixmap,
)
from codexbar_gui.popover import UsagePopover
from codexbar_gui.server_launcher import kill_server, start_server
from codexbar_gui.upstream import ProviderView, fetch_usage_views, find_codexbar_binary
from codexbar_gui.usage_panel import summary_from_views
from codexbar_gui.webapp import DEFAULT_WEB_PORT, start_web, stop_web

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


class _FetchWorker(QThread):
    """Background CLI fetch so tray never freezes on hung codexbar usage."""

    done = Signal(list)

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port

    def run(self) -> None:
        try:
            views = fetch_usage_views(self._host, self._port, prefer_cli=True)
        except Exception:
            logger.warning("background fetch failed", exc_info=True)
            views = []
        self.done.emit(views)


class CodexBarApp:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        refresh_interval_ms: int = REFRESH_INTERVAL_MS,
        web_port: int = DEFAULT_WEB_PORT,
    ) -> None:
        self._host = host
        self._port = port
        self._web_port = web_port
        self._refresh_interval_ms = refresh_interval_ms
        self._app: Optional[QApplication] = None
        self._tray: Optional[QSystemTrayIcon] = None
        self._popover: Optional[UsagePopover] = None
        self._refresh_timer: Optional[QTimer] = None
        self._server_proc: Optional[subprocess.Popen] = None
        self._current_used: Optional[float] = None
        self._current_remaining: Optional[float] = None
        self._session_remaining: Optional[float] = None
        self._weekly_remaining: Optional[float] = None
        self._web_url: Optional[str] = None
        self._fetch: Optional[_FetchWorker] = None

    def run(self) -> int:
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("CodexBar")
        self._app.setQuitOnLastWindowClosed(False)

        binary = find_codexbar_binary()
        logger.info(
            "CodexBar GUI host=%s:%d web_port=%d refresh=%ds binary=%s wayland=%s platform=%s",
            self._host,
            self._port,
            self._web_port,
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

        # Local HTML dashboard (official serve has JSON only — GET / is 404).
        ok_web, web_msg = start_web(port=self._web_port)
        if ok_web:
            self._web_url = web_msg
            logger.info("Web UI: %s", web_msg)
            print(f"CodexBar Web UI: {web_msg}", flush=True)
        else:
            logger.warning("Web UI not started: %s", web_msg)
            print(f"CodexBar Web UI failed: {web_msg}", file=sys.stderr, flush=True)

        self._popover = UsagePopover(self._host, self._port, web_url=self._web_url)
        self._init_tray()
        self._start_server()
        self._refresh_data()
        self._start_refresh_timer()

        if self._tray is None or not self._tray.isSystemTrayAvailable():
            QMessageBox.warning(
                None,
                "CodexBar",
                "No system tray available.\nOpening usage window instead."
                + (f"\nWeb: {self._web_url}" if self._web_url else ""),
            )
            self._popover.show_at_cursor()
        else:
            self._tray.show()
            QTimer.singleShot(300, self._open_popover)

        try:
            return self._app.exec()
        finally:
            self._cleanup()

    def _init_tray(self) -> None:
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(QIcon(make_simple_pixmap("C", DEFAULT_TRAY_SIZE, "#89b4fa")))
        tip = "CodexBar — click for usage"
        if self._web_url:
            tip += f"\nWeb: {self._web_url}"
        self._tray.setToolTip(tip)
        # Do NOT use setContextMenu(QMenu) with QWidgetActions on Wayland.
        self._tray.activated.connect(self._on_activated)

    def _open_popover(self) -> None:
        if self._popover is None:
            return
        try:
            if self._web_url:
                self._popover.set_web_url(self._web_url)
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
                "(port 8000 unused; default serve is 8080 JSON-only; HTML is :%s)",
                self._port,
                self._web_port,
            )
            return True
        except Exception as exc:
            logger.error("server start: %s", exc)
            return True

    def _refresh_data(self) -> None:
        if self._fetch is not None and self._fetch.isRunning():
            return
        self._fetch = _FetchWorker(self._host, self._port)
        self._fetch.done.connect(self._on_views)
        self._fetch.start()

    def _on_views(self, views: list) -> None:
        try:
            typed: list[ProviderView] = list(views)
            used, tip = summary_from_views(typed)
            self._current_used = used
            rems = [
                v.headline_remaining
                for v in typed
                if v.ok and v.headline_remaining is not None
            ]
            self._current_remaining = min(rems) if rems else None
            # Dual-bar tray from first ok provider (official: session + weekly)
            self._session_remaining = None
            self._weekly_remaining = None
            for v in typed:
                if not v.ok:
                    continue
                if v.primary is not None:
                    self._session_remaining = v.primary.remaining_percent
                if v.secondary is not None:
                    self._weekly_remaining = v.secondary.remaining_percent
                break
            err = not typed or all(not v.ok for v in typed)
            self._set_icon(remaining=self._current_remaining, error=err)
            if self._tray:
                extra = f"\nWeb: {self._web_url}" if self._web_url else ""
                if err and not rems:
                    tip = "CLI timeout/empty — click for details" + extra
                else:
                    tip = tip + "\n(click tray icon)" + extra
                self._tray.setToolTip(tip)
        except Exception:
            logger.warning("apply views failed", exc_info=True)
            self._set_icon(error=True)

    def _start_refresh_timer(self) -> None:
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(self._refresh_interval_ms)

    def _set_icon(
        self,
        percent: Optional[float] = None,
        error: bool = False,
        remaining: Optional[float] = None,
    ) -> None:
        if not self._tray:
            return
        rem = remaining if remaining is not None else self._current_remaining
        if rem is None and percent is not None:
            rem = 100.0 - percent
        if (
            not error
            and self._session_remaining is not None
            and self._weekly_remaining is not None
        ):
            icon_pm = paint_dual_window_pixmap(
                primary_remaining=self._session_remaining,
                secondary_remaining=self._weekly_remaining,
                size=DEFAULT_TRAY_SIZE,
            )
        else:
            icon_pm = paint_usage_pixmap(
                remaining=rem, error=error, size=DEFAULT_TRAY_SIZE
            )
        self._tray.setIcon(QIcon(icon_pm))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
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
        if self._fetch is not None and self._fetch.isRunning():
            self._fetch.wait(2000)
        kill_server()
        stop_web()
        if self._popover:
            self._popover.hide()
        if self._tray:
            self._tray.hide()


def main(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    refresh_interval_ms: int = REFRESH_INTERVAL_MS,
    web_port: int = DEFAULT_WEB_PORT,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    return CodexBarApp(host, port, refresh_interval_ms, web_port=web_port).run()


if __name__ == "__main__":
    sys.exit(main())
