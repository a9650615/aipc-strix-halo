"""__main__ entry point for `python3 -m codexbar_gui`."""

from __future__ import annotations

import argparse
import logging
import os
import sys


def _prefer_xcb_for_tray() -> None:
    """On KDE/GNOME Wayland, Qt Tool windows cannot be positioned (move ignored)
    and Popup without a parent fails to map at all.

    Prefer XWayland (xcb) when DISPLAY is available so the tray popover can
    open under the system tray. Opt out with CODEXBAR_NATIVE_WAYLAND=1.
    """
    if os.environ.get("CODEXBAR_NATIVE_WAYLAND", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    wayland = (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )
    if not wayland:
        return
    if not os.environ.get("DISPLAY"):
        return
    # Must be set before QApplication is constructed (any Qt import that
    # creates app, and ideally before QtWidgets is first loaded).
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    os.environ.setdefault("GDK_BACKEND", "x11")


# BEFORE importing tray_app / QtWidgets
_prefer_xcb_for_tray()

from codexbar_gui.tray_app import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    REFRESH_INTERVAL_MS,
    main as _tray_main,
)


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
        default=8787,
        help="Local web UI port (default 8787)",
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
