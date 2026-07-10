"""Cost parse + extra rate windows + multi-provider helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_parse_cost_item_daily() -> None:
    from codexbar_gui.cost import parse_cost_item

    item = {
        "provider": "claude",
        "currencyCode": "USD",
        "historyDays": 30,
        "source": "local",
        "daily": [
            {"date": "2026-07-03", "totalCost": 10.5, "totalTokens": 1_000_000},
            {"date": "2026-07-04", "totalCost": 20.0, "totalTokens": 2_000_000},
        ],
    }
    c = parse_cost_item(item)
    assert c.provider == "claude"
    assert abs(c.period_cost - 30.5) < 0.01
    assert c.period_tokens == 3_000_000
    assert len(c.daily) == 2
    assert "Today" in c.today_line or "$" in c.today_line
    assert "30" in c.period_line


def test_extra_windows_parsed() -> None:
    from codexbar_gui.upstream import parse_upstream_item

    item = {
        "provider": "claude",
        "source": "oauth",
        "usage": {
            "primary": {
                "usedPercent": 18,
                "windowMinutes": 300,
                "resetsAt": "2099-01-01T00:00:00Z",
            },
            "secondary": {
                "usedPercent": 8,
                "windowMinutes": 10080,
                "resetsAt": "2099-07-01T00:00:00Z",
            },
            "extraRateWindows": [
                {
                    "id": "designs",
                    "title": "Designs",
                    "window": {
                        "usedPercent": 0,
                        "windowMinutes": 10080,
                        "resetsAt": "2099-07-01T00:00:00Z",
                    },
                },
                {
                    "id": "daily-routines",
                    "title": "Daily Routines",
                    "window": {
                        "usedPercent": 0,
                        "windowMinutes": 1440,
                        "resetDescription": "Off-peak",
                    },
                },
            ],
        },
    }
    v = parse_upstream_item(item)
    assert v.primary is not None
    assert len(v.extra_windows) == 2
    assert v.extra_windows[0].label == "Designs"
    assert v.extra_windows[0].remaining_percent == 100.0
    assert "Daily" in v.extra_windows[1].label
    assert len(v.all_windows()) >= 4


def test_pace_bar_paints() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.popover import _PaceBar

    _ = QApplication.instance() or QApplication([])
    bar = _PaceBar(remaining=82.0, expected_used=30.0)
    bar.resize(200, 10)
    pm = bar.grab()
    assert not pm.isNull()


def test_enabled_providers_default() -> None:
    from codexbar_gui.upstream import enabled_providers_from_config

    ids = enabled_providers_from_config()
    assert isinstance(ids, list)
    assert ids  # at least codex fallback or config
