#!/usr/bin/env python3
"""Headless logic tests for CodexBar GUI (no tray required)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))

# Allow painting without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_imports() -> None:
    from codexbar_gui.tray_app import CodexBarApp
    from codexbar_gui.usage_panel import UsagePanel, summary_from_data
    from codexbar_gui.icon_updater import generate_svg, get_color_for_percent, paint_usage_pixmap
    from codexbar_gui.config_dialog import ConfigDialog
    from codexbar_gui.server_launcher import check_server, start_server

    assert CodexBarApp is not None
    assert UsagePanel is not None
    assert summary_from_data is not None
    assert callable(generate_svg)
    assert callable(get_color_for_percent)
    assert callable(paint_usage_pixmap)
    assert ConfigDialog is not None
    assert callable(check_server)
    assert callable(start_server)


def test_color_thresholds() -> None:
    from codexbar_gui.icon_updater import get_color_for_percent

    assert get_color_for_percent(0) == "#27ae60"
    assert get_color_for_percent(49) == "#27ae60"
    assert get_color_for_percent(51) == "#f39c12"
    assert get_color_for_percent(81) == "#e74c3c"


def test_svg_and_paint() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.icon_updater import generate_svg, paint_usage_pixmap

    app = QApplication.instance() or QApplication([])
    del app
    svg = generate_svg(42.0)
    assert "svg" in svg
    pm = paint_usage_pixmap(percent=42.0, error=False, size=24)
    assert not pm.isNull()
    err = paint_usage_pixmap(error=True, size=24)
    assert not err.isNull()


def test_summary_from_data() -> None:
    from codexbar_gui.usage_panel import summary_from_data

    data = [
        {
            "provider": "claude",
            "snapshot": {
                "status": "ok",
                "primary": {"used_percent": 42.0, "reset_description": "in 3h"},
            },
        },
        {
            "provider": "openai",
            "snapshot": {"status": "no-api-key", "primary": None},
        },
        {
            "provider": "codex",
            "snapshot": {
                "status": "ok",
                "primary": {"used_percent": 0.9},  # fraction → 90%
            },
        },
    ]
    max_pct, tip = summary_from_data(data)
    assert max_pct == 90.0
    assert "claude" in tip
    assert "CodexBar" in tip


def test_detail_text() -> None:
    from codexbar_gui.usage_panel import UsagePanel

    text = UsagePanel._detail_text(
        "claude",
        {
            "status": "ok",
            "primary": {"used_percent": 10, "reset_description": "soon"},
            "error": None,
            "identity": {"account_email": "a@b.c"},
        },
    )
    assert "claude" in text
    assert "10%" in text or "soon" in text
