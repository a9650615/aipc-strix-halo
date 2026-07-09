"""__main__ entry point for `python3 -m codexbar_gui`."""

from __future__ import annotations

import argparse
import logging
import sys

from codexbar_gui.tray_app import DEFAULT_HOST, DEFAULT_PORT, REFRESH_INTERVAL_MS, main as _tray_main


def entry_point(argv: list[str] | None = None) -> int:
    """Entry point compatible with pyproject.toml [project.scripts]."""
    parser = argparse.ArgumentParser(description="CodexBar system tray GUI")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Usage server host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Usage server port")
    parser.add_argument(
        "--refresh-interval",
        type=int,
        default=REFRESH_INTERVAL_MS // 1000,
        help="Refresh interval in seconds",
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
    return _tray_main(
        host=args.host,
        port=args.port,
        refresh_interval_ms=max(5, args.refresh_interval) * 1000,
    )


if __name__ == "__main__":
    sys.exit(entry_point())
