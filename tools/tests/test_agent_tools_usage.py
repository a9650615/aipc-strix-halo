"""Shipped agent-tools-usage path: CLI scope + normalize + live/fail-soft."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "modules/agent-tools-usage/files/usr/lib/aipc-agent"
sys.path.insert(0, str(PKG))

os.environ.setdefault("AIPC_USAGE_TIMEOUT", "20")


def test_cli_provider_default_is_codex(monkeypatch) -> None:
    from aipc_agent_tools_usage.usage import _cli_provider_ids

    monkeypatch.delenv("CODEXBAR_PROVIDER", raising=False)
    monkeypatch.delenv("CODEXBAR_ALL_PROVIDERS", raising=False)
    assert _cli_provider_ids(None) == ["codex"]
    assert _cli_provider_ids(["claude"]) == ["claude"]
    monkeypatch.setenv("CODEXBAR_ALL_PROVIDERS", "1")
    assert _cli_provider_ids(None) is None


def test_from_official_cli_invokes_provider_and_web_timeout(monkeypatch) -> None:
    """Shipped fetcher must pass --provider codex and --web-timeout (no hang-all)."""
    from aipc_agent_tools_usage import usage as u

    monkeypatch.delenv("CODEXBAR_ALL_PROVIDERS", raising=False)
    monkeypatch.delenv("CODEXBAR_PROVIDER", raising=False)

    sample = json.dumps(
        [
            {
                "provider": "codex",
                "source": "oauth",
                "usage": {
                    "primary": {"usedPercent": 10, "windowMinutes": 300},
                    "secondary": {"usedPercent": 50, "windowMinutes": 10080},
                    "accountEmail": "t@example.com",
                    "loginMethod": "plus",
                },
            }
        ]
    )

    def fake_run(cmd, **kwargs):
        assert cmd[0].endswith("codexbar") or "codexbar" in cmd[0]
        assert "usage" in cmd
        assert "--format" in cmd and "json" in cmd
        assert "--web-timeout" in cmd
        assert "--provider" in cmd and "codex" in cmd
        m = MagicMock()
        m.stdout = sample
        m.stderr = ""
        m.returncode = 0
        return m

    monkeypatch.setattr(u, "_find_codexbar", lambda: "/fake/codexbar")
    monkeypatch.setattr(u.subprocess, "run", fake_run)
    raw = u._from_official_cli(None)
    assert raw and raw[0]["provider"] == "codex"


def test_lookup_usage_normalize_official_shape() -> None:
    from aipc_agent_tools_usage.usage import _normalize_upstream

    raw = [
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
                "accountEmail": "a@b.c",
                "loginMethod": "plus",
            },
        }
    ]
    out = _normalize_upstream(raw, None)
    assert out["status"] == "ok"
    assert out["tool"] == "usage.lookup"
    p = out["providers"][0]
    assert p["remaining_percent"] == 68
    assert p["used_percent"] == 32
    assert p["account"] == "a@b.c"


def test_lookup_usage_live_or_failsoft() -> None:
    """Real entry point: structured ok/error/not_configured — never crash."""
    from aipc_agent_tools_usage.usage import lookup_usage

    result = lookup_usage(None)
    assert result["tool"] == "usage.lookup"
    assert result["status"] in ("ok", "error", "not_configured")
    assert "providers" in result
    if result["status"] == "ok" and result["providers"]:
        p = result["providers"][0]
        assert "remaining_percent" in p or p.get("status") == "error"
        # Must not invent aipc no-api-key success blob as the only story
        assert p.get("status") != "no-api-key"


def test_self_test_entry() -> None:
    from aipc_agent_tools_usage.usage import self_test

    self_test()
