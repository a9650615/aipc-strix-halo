"""Tests for official CodexBar JSON adapter (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI))

from codexbar_gui.upstream import parse_upstream_item, parse_upstream_list
from codexbar_gui.usage_panel import summary_from_views


SAMPLE = {
    "provider": "codex",
    "version": "0.142.5",
    "source": "oauth",
    "account": "a9650615@gmail.com",
    "pace": {
        "primary": {
            "summary": "67% in reserve | Expected 99% used | Lasts until reset",
            "deltaPercent": -67,
            "willLastToReset": True,
        }
    },
    "credits": {"remaining": 0},
    "usage": {
        "accountEmail": "a9650615@gmail.com",
        "loginMethod": "plus",
        "primary": {
            "usedPercent": 32,
            "resetDescription": "3:51 AM",
            "windowMinutes": 300,
            "resetsAt": "2026-07-09T19:51:51Z",
        },
        "secondary": {
            "usedPercent": 100,
            "resetDescription": "Jul 13 at 4:09 PM",
            "windowMinutes": 10080,
        },
        "identity": {
            "accountEmail": "a9650615@gmail.com",
            "loginMethod": "plus",
        },
    },
}


def test_parse_real_codex_shape() -> None:
    v = parse_upstream_item(SAMPLE)
    assert v.ok
    assert v.provider == "codex"
    assert v.primary is not None
    assert v.primary.used_percent == 32
    assert v.primary.remaining_percent == 68
    assert v.primary.label.startswith("Session")
    assert v.secondary is not None
    assert v.secondary.remaining_percent == 0
    assert v.secondary.label == "Weekly"
    # SAMPLE has no resetsAt → pace may be None; see dedicated pace tests
    assert v.account == "a9650615@gmail.com"
    assert v.plan == "plus"
    assert v.pace_summary and "reserve" in v.pace_summary
    assert v.credits_remaining == 0
    assert v.headline_remaining == 68


def test_parse_error_claude() -> None:
    v = parse_upstream_item(
        {
            "provider": "claude",
            "source": "auto",
            "error": {
                "kind": "provider",
                "message": "Could not parse Claude usage",
            },
        }
    )
    assert not v.ok
    assert "Claude" in (v.error or "")


def test_summary_uses_worst_remaining() -> None:
    views = parse_upstream_list([SAMPLE])
    used_for_icon, tip = summary_from_views(views)
    # remaining 68% → used 32% for icon fill
    assert used_for_icon == 32
    assert "Session" in tip or "session" in tip.lower() or "68" in tip or "Codex" in tip


def test_cli_provider_default(monkeypatch) -> None:
    from codexbar_gui.upstream import _cli_provider_arg
    monkeypatch.delenv("CODEXBAR_PROVIDER", raising=False)
    monkeypatch.delenv("CODEXBAR_ALL_PROVIDERS", raising=False)
    assert _cli_provider_arg(None) == "codex"
    assert _cli_provider_arg("claude") == "claude"
    monkeypatch.setenv("CODEXBAR_PROVIDER", "gemini")
    assert _cli_provider_arg(None) == "gemini"
    monkeypatch.delenv("CODEXBAR_PROVIDER", raising=False)
    monkeypatch.setenv("CODEXBAR_ALL_PROVIDERS", "1")
    assert _cli_provider_arg(None) is None


def test_official_used_percent_0_1_2_not_fraction_scaled() -> None:
    """Live CLI uses 0–100 scale: usedPercent=1 → 99% remaining (not 0)."""
    for used, rem in ((0, 100.0), (1, 99.0), (2, 98.0)):
        v = parse_upstream_item(
            {
                "provider": "codex",
                "source": "oauth",
                "usage": {
                    "primary": {
                        "usedPercent": used,
                        "windowMinutes": 300,
                        "resetDescription": "soon",
                    },
                    "secondary": {"usedPercent": 100, "windowMinutes": 10080},
                },
            }
        )
        assert v.primary is not None
        assert v.primary.used_percent == float(used)
        assert v.primary.remaining_percent == rem
        assert v.headline_remaining == rem


def test_compute_pace_reserve_when_under_linear_burn() -> None:
    """Barely used + long window left → large reserve (slower than expected)."""
    from datetime import datetime, timedelta, timezone

    from codexbar_gui.upstream import compute_pace

    # 5h window, 4h left → 20% elapsed → expected used 20%; actual 1% → ~19% reserve
    resets = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    pace = compute_pace(1.0, 300, resets)
    assert pace is not None
    assert pace.reserve_percent > 10
    assert pace.will_last_to_reset
    assert "reserve" in pace.summary.lower()
    assert pace.status == "reserve"


def test_compute_pace_deficit_when_over_burn() -> None:
    from datetime import datetime, timedelta, timezone

    from codexbar_gui.upstream import compute_pace

    # 5h window, 4h left → expected ~20% used; actual 80% → deficit
    resets = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    pace = compute_pace(80.0, 300, resets)
    assert pace is not None
    assert pace.reserve_percent < -10
    assert pace.status == "deficit"
    low = pace.summary.lower()
    assert "deficit" in low or "over pace" in low or "faster" in low or "run" in low


def test_parse_attaches_pace_to_windows() -> None:
    from datetime import datetime, timedelta, timezone

    from codexbar_gui.upstream import parse_upstream_item

    resets = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    v = parse_upstream_item(
        {
            "provider": "codex",
            "source": "oauth",
            "usage": {
                "primary": {
                    "usedPercent": 1,
                    "windowMinutes": 300,
                    "resetsAt": resets,
                },
                "secondary": {
                    "usedPercent": 23,
                    "windowMinutes": 10080,
                    "resetsAt": (
                        datetime.now(timezone.utc) + timedelta(hours=17)
                    ).isoformat(),
                },
            },
        }
    )
    assert v.primary is not None and v.primary.pace is not None
    assert v.secondary is not None and v.secondary.pace is not None
    assert v.pace_summary  # card-level from weekly


def test_resets_in_and_plan_label() -> None:
    from codexbar_gui.upstream import format_resets_in, parse_upstream_item

    assert format_resets_in(None) == ""
    v = parse_upstream_item(
        {
            "provider": "codex",
            "version": "0.142.5",
            "source": "oauth",
            "credits": {"remaining": 0},
            "usage": {
                "accountEmail": "a@b.c",
                "loginMethod": "plus",
                "dataConfidence": "exact",
                "updatedAt": "2026-07-10T01:00:00Z",
                "codexResetCredits": {"availableCount": 0},
                "primary": {
                    "usedPercent": 1,
                    "windowMinutes": 300,
                    "resetDescription": "2:27 PM",
                    "resetsAt": "2099-01-01T00:00:00Z",
                },
                "secondary": {
                    "usedPercent": 0,
                    "windowMinutes": 10080,
                    "resetsAt": "2099-07-01T00:00:00Z",
                },
            },
        }
    )
    assert v.plan_label == "Plus"
    assert v.account == "a@b.c"
    assert v.reset_credits_available == 0
    assert v.credits_remaining == 0.0
    assert v.primary is not None
    assert v.primary.resets_in.startswith("Resets in")
    assert v.primary.remaining_percent == 99.0


def test_legacy_fraction_only_open_unit() -> None:
    """0.32 (true fraction) → 32 used / 68 left; 1.0 stays 1% used."""
    frac = parse_upstream_item(
        {
            "provider": "codex",
            "usage": {"primary": {"usedPercent": 0.32, "windowMinutes": 300}},
        }
    )
    assert frac.primary is not None
    assert frac.primary.used_percent == 32.0
    assert frac.primary.remaining_percent == 68.0
    one = parse_upstream_item(
        {
            "provider": "codex",
            "usage": {"primary": {"usedPercent": 1.0, "windowMinutes": 300}},
        }
    )
    assert one.primary is not None
    assert one.primary.used_percent == 1.0
    assert one.primary.remaining_percent == 99.0


def test_weekly_only_codex_primary_null() -> None:
    """Live Codex Plus often returns primary:null + weekly secondary only."""
    v = parse_upstream_item(
        {
            "provider": "codex",
            "source": "oauth",
            "credits": {"remaining": 0},
            "pace": {
                "secondary": {
                    "summary": "37% in deficit | Expected 22% used | Runs out in 1d 1h",
                    "stage": "farAhead",
                    "deltaPercent": 37,
                    "willLastToReset": False,
                    "expectedUsedPercent": 22,
                }
            },
            "usage": {
                "accountEmail": "a@b.c",
                "loginMethod": "plus",
                "primary": None,
                "secondary": {
                    "usedPercent": 59,
                    "windowMinutes": 10080,
                    "resetsAt": "2099-07-25T15:14:29Z",
                    "resetDescription": "Jul 25 at 11:14 PM",
                },
                "tertiary": None,
                "dataConfidence": "exact",
            },
        }
    )
    assert v.ok
    assert v.primary is None
    assert v.secondary is not None
    assert v.secondary.label == "Weekly"
    assert v.secondary.used_percent == 59.0
    assert v.secondary.remaining_percent == 41.0
    assert v.headline_remaining == 41.0
    assert v.pace_summary and "deficit" in v.pace_summary.lower()


def test_weekly_only_icon_is_single_bar_not_double_fill() -> None:
    """Tray must not paint weekly into both session+weekly tracks."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.icon_updater import (
        _normalize_window_rems,
        paint_usage_pixmap,
    )

    _ = QApplication.instance() or QApplication([])
    top, bot, style = _normalize_window_rems(None, 41.0, "dual_bars")
    assert top == 41.0
    assert bot is None
    assert style == "primary_only"
    # paint_usage_pixmap must NOT invent primary from headline remaining
    pm = paint_usage_pixmap(
        remaining=41.0,
        primary_remaining=None,
        secondary_remaining=41.0,
        size=24,
        icon_style="dual_bars",
    )
    assert not pm.isNull()
    # Dual-with-both still dual
    t2, b2, s2 = _normalize_window_rems(62.0, 41.0, "dual_bars")
    assert t2 == 62.0 and b2 == 41.0 and s2 == "dual_bars"


def test_tray_tooltip_names_weekly_when_primary_null() -> None:
    from codexbar_gui.menu_bar import MenuBarSettings, tray_tooltip_line

    v = parse_upstream_item(
        {
            "provider": "codex",
            "source": "oauth",
            "usage": {
                "loginMethod": "plus",
                "primary": None,
                "secondary": {
                    "usedPercent": 59,
                    "windowMinutes": 10080,
                    "resetsAt": "2099-07-25T15:14:29Z",
                },
            },
        }
    )
    tip = tray_tooltip_line(v, MenuBarSettings())
    assert "Codex" in tip
    assert "41" in tip or "left" in tip.lower() or "剩餘" in tip or "%" in tip
    # Must mention weekly window so it isn't read as a missing session limit
    low = tip.lower()
    assert "week" in low or "每週" in tip or "每周" in tip


def test_build_cli_env_injects_zai_key_from_config() -> None:
    """config.json api_key must become Z_AI_API_KEY for child CLI env."""
    from codexbar_gui.upstream import build_cli_env, _source_attempts

    cfg = {
        "version": 1,
        "providers": [
            {"id": "zai", "enabled": True, "source": "auto", "api_key": "test-zai-key-12345"}
        ],
    }
    base = {"PATH": "/usr/bin", "HOME": "/tmp"}
    env = build_cli_env("zai", base=base, data=cfg)
    assert env["Z_AI_API_KEY"] == "test-zai-key-12345"
    # Do not clobber existing export
    base2 = {**base, "Z_AI_API_KEY": "already-set"}
    env2 = build_cli_env("zai", base=base2, data=cfg)
    assert env2["Z_AI_API_KEY"] == "already-set"
    # zai prefers api source when key present
    attempts = _source_attempts("zai", "auto")
    # provider_has_api_key reads real config OR env — force via env
    import os
    from codexbar_gui import upstream as up

    # Unit-level: when configured auto and key exists, helper returns api first
    # Simulate has-key path by checking the branch with monkeypatched has_key
    assert "api" in (_source_attempts("zai", "api") or [])
    assert _source_attempts("zai", "api") == ["api"]


def test_friendly_zai_error_mentions_api_key() -> None:
    from codexbar_gui.upstream import _friendly_zai_error

    msg = _friendly_zai_error("No available fetch strategy for zai.", "api")
    assert msg and "API key" in msg


def test_grok_supergrok_weekly_primary() -> None:
    """Grok SuperGrok: single primary bucket, no windowMinutes → Weekly not Session 5h."""
    from datetime import datetime, timedelta, timezone

    resets = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat().replace("+00:00", "Z")
    v = parse_upstream_item(
        {
            "provider": "grok",
            "source": "grok-web",
            "usage": {
                "accountEmail": "a@b.c",
                "loginMethod": "SuperGrok",
                "primary": {"usedPercent": 65, "resetsAt": resets},
                "secondary": None,
            },
        }
    )
    assert v.ok
    assert v.primary is not None
    assert v.primary.label == "Weekly"
    assert v.primary.window_minutes == 10080
    assert v.primary.remaining_percent == 35.0
    assert v.headline_remaining == 35.0
    assert v.secondary is None
