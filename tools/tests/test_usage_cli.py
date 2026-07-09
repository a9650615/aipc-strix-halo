"""Tests for `aipc usage` command group registration and LiteLLM helpers."""

from __future__ import annotations

from click.testing import CliRunner

from aipc_lib import cli
from aipc_lib.codexbar_usage import (
    aggregate_by_provider,
    canonical_provider,
    ensure_codexbar_on_path,
    usage_cli,
    UsageRow,
)


def test_usage_group_registered_on_main() -> None:
    assert "usage" in cli.main.commands


def test_usage_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["usage", "--help"])
    assert result.exit_code == 0
    for name in ("list", "aggregate", "show", "cost", "serve", "gui", "providers", "aliases"):
        assert name in result.output


def test_usage_aliases_command() -> None:
    runner = CliRunner()
    result = runner.invoke(usage_cli, ["aliases"])
    assert result.exit_code == 0
    assert "lemonade" in result.output
    assert "ollama" in result.output


def test_canonical_provider() -> None:
    assert canonical_provider("lemonade") == "ollama"
    assert canonical_provider("unknown-xyz") is None


def test_aggregate_by_provider() -> None:
    rows = [
        UsageRow("openai", "gpt", 10, 0.1, 2),
        UsageRow("openai", "o1", 5, 0.2, 1),
        UsageRow("anthropic", "sonnet", 3, 0.05, 1),
    ]
    agg = aggregate_by_provider(rows)
    assert agg["openai"]["total_tokens"] == 15
    assert agg["openai"]["models"] == 2
    assert agg["anthropic"]["request_count"] == 1


def test_ensure_codexbar_on_path_finds_module_tree() -> None:
    path = ensure_codexbar_on_path()
    assert path is not None
    import codexbar_usage

    assert codexbar_usage.__version__


def test_usage_providers_lists_registry() -> None:
    runner = CliRunner()
    result = runner.invoke(usage_cli, ["providers"])
    assert result.exit_code == 0
    assert "claude" in result.output
    assert "fetcher" in result.output.lower() or "yes" in result.output
