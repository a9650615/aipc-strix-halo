"""Tests for codexbar_usage.cli — Click CLI structure and parameter parsing."""

from __future__ import annotations

import os
import sys
from typing import Generator

import pytest
from click.testing import CliRunner

from codexbar_usage.cli import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_codexbar_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Remove all CODEXBAR_* env vars to avoid leaking state into tests."""
    for key in [k for k in os.environ if k.startswith("CODEXBAR_")]:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Test: CLI group exists and shows help
# ---------------------------------------------------------------------------

def test_cli_help(runner: CliRunner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "AI coding usage tracker" in result.output


def test_cli_version(runner: CliRunner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_prog_name(runner: CliRunner):
    result = runner.invoke(cli, ["--version"])
    assert "aipc-usage" in result.output


# ---------------------------------------------------------------------------
# Test: subcommand discovery
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("subcommand", ["usage", "cost", "serve", "config", "cache"])
def test_subcommand_exists(runner: CliRunner, subcommand: str):
    result = runner.invoke(cli, [subcommand, "--help"])
    assert result.exit_code == 0, f"{subcommand} --help failed: {result.output}"
    assert result.output


# ---------------------------------------------------------------------------
# Test: usage command
# ---------------------------------------------------------------------------

def test_usage_help(runner: CliRunner):
    result = runner.invoke(cli, ["usage", "--help"])
    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--format" in result.output
    assert "--source" in result.output


def test_usage_format_choices(runner: CliRunner):
    result = runner.invoke(cli, ["usage", "--help"])
    for fmt in ("text", "json", "cards", "table"):
        assert fmt in result.output


def test_usage_runs_with_no_providers(runner: CliRunner):
    """With no config file, the command should report no providers and exit cleanly."""
    result = runner.invoke(cli, ["usage"])
    assert result.exit_code == 0


def test_usage_provider_filter(runner: CliRunner):
    """--provider should accept comma-separated values."""
    result = runner.invoke(cli, ["usage", "--provider", "claude,openai"])
    assert result.exit_code == 0


def test_usage_json_format(runner: CliRunner):
    result = runner.invoke(cli, ["usage", "-f", "json"])
    assert result.exit_code == 0


def test_usage_table_format(runner: CliRunner):
    result = runner.invoke(cli, ["usage", "-f", "table"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test: cost command
# ---------------------------------------------------------------------------

def test_cost_help(runner: CliRunner):
    result = runner.invoke(cli, ["cost", "--help"])
    assert result.exit_code == 0
    assert "--days" in result.output
    assert "--provider" in result.output
    assert "--group-by" in result.output


def test_cost_days_range(runner: CliRunner):
    result = runner.invoke(cli, ["cost", "--help"])
    assert "1" in result.output
    assert "365" in result.output


# ---------------------------------------------------------------------------
# Test: serve command
# ---------------------------------------------------------------------------

def test_serve_help(runner: CliRunner):
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--refresh-interval" in result.output


def test_serve_default_port(runner: CliRunner):
    result = runner.invoke(cli, ["serve", "--help"])
    assert "8080" in result.output


# ---------------------------------------------------------------------------
# Test: config subcommands
# ---------------------------------------------------------------------------

def test_config_help(runner: CliRunner):
    result = runner.invoke(cli, ["config", "--help"])
    assert result.exit_code == 0
    assert "enable" in result.output
    assert "disable" in result.output
    assert "validate" in result.output
    assert "dump" in result.output
    assert "set-api-key" in result.output


def test_config_enable(runner: CliRunner):
    result = runner.invoke(cli, ["config", "enable", "claude"])
    assert result.exit_code == 0
    assert "enabled" in result.output.lower()
    assert "claude" in result.output


def test_config_disable(runner: CliRunner):
    result = runner.invoke(cli, ["config", "disable", "openai"])
    assert result.exit_code == 0
    assert "disabled" in result.output.lower()
    assert "openai" in result.output


def test_config_validate(runner: CliRunner):
    result = runner.invoke(cli, ["config", "validate"])
    # Exit code depends on whether config file exists; we just check it runs.
    assert result.exit_code in (0, 1)


def test_config_dump(runner: CliRunner):
    result = runner.invoke(cli, ["config", "dump"])
    assert result.exit_code == 0
    # Should output valid JSON (even if empty)
    import json
    try:
        data = json.loads(result.output)
        assert "version" in data
    except json.JSONDecodeError:
        pytest.fail("config dump did not produce valid JSON")


def test_config_set_api_key(runner: CliRunner):
    result = runner.invoke(cli, [
        "config", "set-api-key",
        "-p", "claude",
        "--api-key", "sk-ant-test-key-123",
    ])
    assert result.exit_code == 0
    assert "set" in result.output.lower()
    assert "claude" in result.output


def test_config_set_api_key_requires_key(runner: CliRunner):
    result = runner.invoke(cli, [
        "config", "set-api-key",
        "-p", "claude",
    ])
    assert result.exit_code == 1
    assert "required" in result.output.lower()


def test_config_set_api_key_no_enable(runner: CliRunner):
    result = runner.invoke(cli, [
        "config", "set-api-key",
        "-p", "claude",
        "--api-key", "sk-ant-test-key",
        "--no-enable",
    ])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test: cache subcommands
# ---------------------------------------------------------------------------

def test_cache_help(runner: CliRunner):
    result = runner.invoke(cli, ["cache", "--help"])
    assert result.exit_code == 0
    assert "clear" in result.output


def test_cache_clear(runner: CliRunner):
    result = runner.invoke(cli, ["cache", "clear"])
    assert result.exit_code == 0


def test_cache_clear_all(runner: CliRunner):
    result = runner.invoke(cli, ["cache", "clear", "--all"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test: _parse_csv helper
# ---------------------------------------------------------------------------

def test_parse_csv_empty():
    from codexbar_usage.cli import _parse_csv
    assert _parse_csv(None) is None
    assert _parse_csv("") is None


def test_parse_csv_single():
    from codexbar_usage.cli import _parse_csv
    assert _parse_csv("claude") == ["claude"]


def test_parse_csv_multiple():
    from codexbar_usage.cli import _parse_csv
    result = _parse_csv("claude,openai,gemini")
    assert result == ["claude", "openai", "gemini"]


def test_parse_csv_strips_whitespace():
    from codexbar_usage.cli import _parse_csv
    result = _parse_csv(" claude , openai ")
    assert result == ["claude", "openai"]


def test_parse_csv_skips_empty():
    from codexbar_usage.cli import _parse_csv
    result = _parse_csv("claude,,openai,")
    assert result == ["claude", "openai"]
