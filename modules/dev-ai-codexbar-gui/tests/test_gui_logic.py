#!/usr/bin/env python3
"""Headless logic tests for CodexBar GUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_imports() -> None:
    from codexbar_gui.tray_app import CodexBarApp
    from codexbar_gui.usage_panel import UsagePanel
    from codexbar_gui.upstream import parse_upstream_item, find_codexbar_binary
    from codexbar_gui.icon_updater import paint_usage_pixmap

    assert CodexBarApp and UsagePanel and parse_upstream_item and paint_usage_pixmap
    # binary may or may not exist in CI
    _ = find_codexbar_binary()


def test_color_and_paint() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.icon_updater import get_color_for_percent, paint_usage_pixmap

    _ = QApplication.instance() or QApplication([])
    assert get_color_for_percent(10) == "#27ae60"
    assert not paint_usage_pixmap(percent=32).isNull()


def test_summary_from_views_official() -> None:
    from codexbar_gui.upstream import parse_upstream_list
    from codexbar_gui.usage_panel import summary_from_views

    data = [
        {
            "provider": "codex",
            "source": "oauth",
            "usage": {
                "primary": {
                    "usedPercent": 32,
                    "resetDescription": "soon",
                    "windowMinutes": 300,
                },
                "secondary": {"usedPercent": 100, "windowMinutes": 10080},
            },
            "pace": {"primary": {"summary": "67% in reserve"}},
        }
    ]
    views = parse_upstream_list(data)
    used, tip = summary_from_views(views)
    assert used == 32  # icon fill = used
    assert "Codex" in tip or "codex" in tip.lower()
    assert "68" in tip or "session" in tip.lower() or "Session" in tip
