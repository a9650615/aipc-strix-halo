from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from codexbar_usage.config import CodexBarConfig, ProviderConfig, save_config
from codexbar_usage.registry import provider_by_id


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "codexbar"
    config_dir.mkdir()
    monkeypatch.setenv("CODEXBAR_CONFIG", str(config_dir))
    return config_dir


def test_provider_descriptors_expose_upstream_fetch_plan_fields() -> None:
    codex = provider_by_id("codex")
    claude = provider_by_id("claude")
    litellm = provider_by_id("litellm")

    assert codex is not None
    assert claude is not None
    assert litellm is not None

    assert codex.metadata.display_name == "Codex"
    assert codex.cli.name == "codex"
    assert codex.fetch_plan.source_modes == {"auto", "cli", "local"}
    assert [strategy.kind for strategy in codex.fetch_plan.strategies] == ["cli", "local"]

    assert claude.fetch_plan.source_modes == {"auto", "api", "local"}
    assert [strategy.kind for strategy in claude.fetch_plan.strategies] == ["api", "local"]

    assert litellm.fetch_plan.source_modes == {"auto", "api"}
    assert [strategy.kind for strategy in litellm.fetch_plan.strategies] == ["api"]


def test_build_usage_payloads_returns_upstream_cli_payload_shape(tmp_config_dir: Path) -> None:
    save_config(
        CodexBarConfig(
            providers=[ProviderConfig(id="claude", enabled=True, api_key="sk-ant-test")]
        )
    )

    from codexbar_usage.cli import build_usage_payloads

    payloads = build_usage_payloads(providers=["claude"], source_mode="auto")

    assert [payload["provider"] for payload in payloads] == ["claude"]
    payload = payloads[0]
    assert payload["source"] in {"api", "local", "unsupported", "config"}
    assert "usage" in payload
    assert "status" in payload
    assert "error" in payload or payload["usage"] is not None or payload["status"] is not None


def test_cost_scanner_parses_codex_jsonl_sessions(tmp_path: Path) -> None:
    from codexbar_usage.cost import load_token_costs

    sessions = tmp_path / ".codex" / "sessions" / "2026" / "07" / "09"
    sessions.mkdir(parents=True)
    log_file = sessions / "rollout-test.jsonl"
    log_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-07-09T12:00:00Z",
                        "cwd": "/repo/a",
                        "model": "gpt-5-codex",
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                        "cost_usd": 0.75,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-09T13:00:00Z",
                        "cwd": "/repo/a",
                        "model": "gpt-5-codex",
                        "usage": {"input_tokens": 20, "output_tokens": 30},
                        "cost_usd": 0.25,
                    }
                ),
            ]
        )
        + "\n"
    )

    snapshot = load_token_costs(
        provider_id="codex",
        base_path=tmp_path,
        now=datetime(2026, 7, 10, tzinfo=timezone.utc),
        history_days=30,
    )

    assert snapshot.session_tokens == 200
    assert snapshot.session_cost_usd == 1.0
    assert snapshot.last_30_days_tokens == 200
    assert snapshot.last_30_days_cost_usd == 1.0
    assert snapshot.projects[0].name == "/repo/a"


def test_cost_scanner_parses_claude_jsonl_sessions(tmp_path: Path) -> None:
    from codexbar_usage.cost import load_token_costs

    projects = tmp_path / ".claude" / "projects"
    projects.mkdir(parents=True)
    log_file = projects / "project.jsonl"
    log_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-07-09T09:00:00Z",
                        "cwd": "/repo/b",
                        "model": "claude-sonnet",
                        "usage": {"input_tokens": 40, "output_tokens": 10},
                        "cost_usd": 0.5,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-09T10:00:00Z",
                        "cwd": "/repo/b",
                        "model": "claude-opus",
                        "usage": {"input_tokens": 30, "output_tokens": 20},
                        "cost_usd": 1.25,
                    }
                ),
            ]
        )
        + "\n"
    )

    snapshot = load_token_costs(
        provider_id="claude",
        base_path=tmp_path,
        now=datetime(2026, 7, 10, tzinfo=timezone.utc),
        history_days=30,
    )

    assert snapshot.session_tokens == 100
    assert snapshot.session_cost_usd == 1.75
    assert snapshot.last_30_days_tokens == 100
    assert snapshot.last_30_days_cost_usd == 1.75
    assert snapshot.projects[0].name == "/repo/b"
