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
