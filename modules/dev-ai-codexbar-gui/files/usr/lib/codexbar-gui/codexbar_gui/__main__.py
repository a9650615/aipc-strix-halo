"""__main__ entry point for `python3 -m codexbar_gui`."""

from __future__ import annotations

import argparse
import logging
import os
import sys


def _configure_qt_platform() -> None:
    """Pick a Qt platform that can track the tray across monitors.

    Plasma multi-monitor + fractional scaling: XWayland virtual desktop does
    **not** match KWin logical layout (different origins / DPR). Forcing xcb
    then makes the popover appear on the wrong screen.

    Default: stay on Wayland when available.
    Escape hatch: CODEXBAR_FORCE_XCB=1 (single-monitor / debugging only).
    """
    if os.environ.get("CODEXBAR_FORCE_XCB", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        if os.environ.get("DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            os.environ.setdefault("GDK_BACKEND", "x11")
        return

    # Leave explicit QT_QPA_PLATFORM alone (tests use offscreen, etc.)
    if os.environ.get("QT_QPA_PLATFORM", "").strip():
        return

    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get(
        "XDG_SESSION_TYPE", ""
    ).lower() == "wayland":
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    elif os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


# BEFORE importing tray_app / QtWidgets
_configure_qt_platform()

from codexbar_gui.tray_app import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    REFRESH_INTERVAL_MS,
    main as _tray_main,
)
from codexbar_gui.webapp import DEFAULT_WEB_PORT  # noqa: E402


def entry_point(argv: list[str] | None = None) -> int:
    """Entry point compatible with pyproject.toml [project.scripts]."""
    parser = argparse.ArgumentParser(description="CodexBar system tray GUI")
    parser.add_argument("--host", default=DEFAULT_HOST, help="codexbar serve host")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="codexbar serve port (default 8080)"
    )
    parser.add_argument(
        "--refresh-interval",
        type=int,
        default=REFRESH_INTERVAL_MS // 1000,
        help="Refresh interval in seconds",
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Only run local web dashboard (no tray)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help="Local web UI + /usage JSON port (default 8080; replaces aipc-usage)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    if args.web_only:
        from codexbar_gui.webapp import main as web_main

        sys.argv = [
            "codexbar-gui-web",
            "--host",
            args.host,
            "--port",
            str(args.web_port),
        ]
        return web_main()
    return _tray_main(
        host=args.host,
        port=args.port,
        refresh_interval_ms=max(5, args.refresh_interval) * 1000,
        web_port=args.web_port,
    )


if __name__ == "__main__":
    sys.exit(entry_point())
