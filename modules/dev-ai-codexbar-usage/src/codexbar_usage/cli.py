"""CLI entry point for aipc-usage.

Provides commands to view AI coding usage, cost, and provider status.
Mirrors the `codexbar` CLI from the original CodexBar tool.

Commands:
    usage   Show usage data for AI coding providers
    cost    Show local token cost usage (Codex + Claude JSONL scans)
    serve   Start HTTP server for usage/cost JSON
    config  Manage provider configuration
    cache   Manage caches

Run `aipc-usage --help` for the full command list.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

import click

from codexbar_usage.config import (
    config_path,
    config_validate,
    load_config,
    set_api_key,
    toggle_provider,
)
from codexbar_usage.fetch import build_usage_payloads, fetch_all_usage
from codexbar_usage.registry import (
    all_providers,
    provider_by_id,
    provider_ids,
)
from codexbar_usage.server import run_server

# ponytail: provider modules use httpx; keep CLI importable without it.
_HAS_HTTPX = False
try:
    import httpx  # noqa: F401  (used lazily below)
    _HAS_HTTPX = True
except ImportError:
    pass


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _parse_csv(value: Optional[str]) -> Optional[List[str]]:
    """Parse a comma-separated string into a list, stripping empty entries."""
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _fetch_usage_snapshots(
    providers: Optional[List[str]] = None,
    source: str = "auto",
) -> List[Dict[str, Any]]:
    """Fetch usage snapshots for the given providers (real provider dispatch)."""
    return fetch_all_usage(providers=providers, source=source)


# Re-export for tests / external callers.
__all_cli_exports__ = ("build_usage_payloads", "cli")


def _render_usage(
    results: List[Dict[str, Any]],
    fmt: str = "cards",
    status: bool = False,
) -> None:
    """Render usage results in the requested format."""
    if fmt == "json":
        from codexbar_usage.ui import render_json
        render_json(results)
        return

    if fmt == "table":
        from codexbar_usage.ui import render_table
        render_table(results)
        return

    # cards (default)
    from codexbar_usage.ui import render_cards
    render_cards(results)


# --------------------------------------------------------------------------- #
#  Top-level group
# --------------------------------------------------------------------------- #

@click.group()
@click.version_option(version="0.1.0", prog_name="aipc-usage")
def cli() -> None:
    """AI coding usage tracker (CodexBar port for Linux).

    Track usage across 50+ AI providers including Codex, Claude, OpenAI,
    Copilot, Gemini, and more.
    """


# --------------------------------------------------------------------------- #
#  usage
# --------------------------------------------------------------------------- #

@cli.command()
@click.option(
    "--provider", "-p", "providers",
    help="Filter by provider ID(s), comma-separated.",
)
@click.option(
    "--format", "-f", "fmt",
    type=click.Choice(["text", "json", "cards", "table"]),
    default="cards",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--source", "-s",
    type=click.Choice(["auto", "cli", "api", "web"]),
    default="auto",
    show_default=True,
    help="Source strategy for fetching usage data.",
)
@click.option(
    "--status", is_flag=True,
    help="Include status page indicators in output.",
)
def usage(providers: Optional[str], fmt: str, source: str, status: bool) -> None:
    """Show usage data for AI coding providers.

    This is the main command, mirroring `codexbar usage` from the original
    CodexBar. Fetches rate-window data (usage percentage, reset time) for
    each configured provider and renders it in the requested format.
    """
    provider_list = _parse_csv(providers)
    results = _fetch_usage_snapshots(provider_list, source)
    if not results:
        click.echo("No providers configured. Run `aipc-usage config dump` to inspect config.")
        sys.exit(0)
    _render_usage(results, fmt, status)


# --------------------------------------------------------------------------- #
#  cost
# --------------------------------------------------------------------------- #

@cli.command()
@click.option(
    "--days", "-d", "days",
    type=click.IntRange(1, 365),
    default=30,
    show_default=True,
    help="Cost history window in days.",
)
@click.option(
    "--provider", "-p",
    help="Filter by provider ID.",
)
@click.option(
    "--group-by",
    type=click.Choice(["project", "model"]),
    help="Group cost data by project or model.",
)
def cost(days: int, provider: Optional[str], group_by: Optional[str]) -> None:
    """Show local token cost usage (Codex + Claude JSONL scans).

    Mirrors `codexbar cost` from the original CodexBar. Scans local JSONL
    log files from Codex and Claude CLI sessions to compute token costs
    over the requested window.
    """
    from codexbar_usage.cost import cost_results_for_cli

    results = cost_results_for_cli(days=days, provider=provider)

    if not results:
        click.echo(f"No cost data found for window: {days} days.")
        sys.exit(0)

    if group_by:
        click.echo(f"Cost data grouped by {group_by}:")
        for r in results:
            pc = r["snapshot"].get("provider_cost", {})
            if group_by == "project":
                for proj in pc.get("projects") or []:
                    click.echo(
                        f"  {r['provider']}/{proj.get('name')}: "
                        f"${float(proj.get('cost_usd', 0)):.4f} "
                        f"({int(proj.get('tokens', 0))} tok)"
                    )
            else:
                cost_total = pc.get("total", 0)
                click.echo(f"  {r['provider']}: ${float(cost_total):.4f}")
    else:
        from codexbar_usage.ui import render_cost_table
        render_cost_table(results)


# --------------------------------------------------------------------------- #
#  serve
# --------------------------------------------------------------------------- #

@cli.command()
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Bind address for the HTTP server.",
)
@click.option(
    "--port", "-P", "port",
    type=int, default=8080,
    show_default=True,
    help="HTTP server port.",
)
@click.option(
    "--refresh-interval",
    type=int, default=60,
    show_default=True,
    help="Refresh interval in seconds.",
)
def serve(host: str, port: int, refresh_interval: int) -> None:
    """Start HTTP server for usage/cost JSON.

    Mirrors `codexbar serve` from the original CodexBar. Exposes:
      GET /health   — server health check
      GET /usage    — usage data (optionally ?provider=xxx)
      GET /cost     — cost data (optionally ?provider=xxx)

    Intended for waybar/GNOME/KDE extensions that poll for usage data.
    """
    run_server(host=host, port=port, refresh_interval=refresh_interval)


# --------------------------------------------------------------------------- #
#  config group
# --------------------------------------------------------------------------- #

@cli.group("config")
def config_cmd() -> None:
    """Manage provider configuration.

    Mirrors `codexbar config` commands from the original CodexBar.
    Config file: ~/.config/codexbar/config.json (XDG-compliant).
    """


@config_cmd.command("enable")
@click.argument("provider_id")
def config_enable(provider_id: str) -> None:
    """Enable a provider."""
    config = load_config()
    toggle_provider(config, provider_id, True)
    click.echo(f"enabled: {provider_id}")


@config_cmd.command("disable")
@click.argument("provider_id")
def config_disable(provider_id: str) -> None:
    """Disable a provider."""
    config = load_config()
    toggle_provider(config, provider_id, False)
    click.echo(f"disabled: {provider_id}")


@config_cmd.command("validate")
def config_validate_cmd() -> None:
    """Validate config file."""
    errors = config_validate()
    if errors:
        for e in errors:
            click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    click.echo(f"Config OK: {config_path()}")


@config_cmd.command("dump")
def config_dump() -> None:
    """Print normalized config JSON."""
    config = load_config()
    click.echo(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))


@config_cmd.command("set-api-key")
@click.option("--provider", "-p", required=True, help="Provider ID.")
@click.option("--api-key", "-k", help="API key (omit to read from --stdin).")
@click.option("--stdin", is_flag=True, help="Read key from stdin.")
@click.option("--no-enable", is_flag=True, help="Don't enable provider after setting key.")
def config_set_api_key(provider: str, api_key: Optional[str], stdin: bool, no_enable: bool) -> None:
    """Set API key for a provider.

    Reads from --api-key, or stdin if --stdin is given. If the provider
    is not yet in the config, it is added as disabled unless --no-enable
    is passed.
    """
    if stdin:
        try:
            api_key = sys.stdin.read().strip()
        except Exception:
            click.echo("Failed to read API key from stdin.", err=True)
            sys.exit(1)

    if not api_key:
        click.echo("--api-key or --stdin is required.", err=True)
        sys.exit(1)

    config = load_config()
    set_api_key(config, provider, api_key)
    if not no_enable:
        toggle_provider(config, provider, True)
    click.echo(f"set API key for: {provider}")


# --------------------------------------------------------------------------- #
#  cache group
# --------------------------------------------------------------------------- #

@cli.group("cache")
def cache_cmd() -> None:
    """Manage caches."""


@cache_cmd.command("clear")
@click.option("--all", "clear_all", is_flag=True, help="Clear all caches.")
@click.option("--cookies", is_flag=True, help="Clear cookie caches.")
@click.option("--cost", is_flag=True, help="Clear cost caches.")
def cache_clear(clear_all: bool, cookies: bool, cost: bool) -> None:
    """Clear local caches.

    Clears in-memory and on-disk caches used by the provider fetchers.
    Cache directories:
      cookies : ~/.config/codexbar/cookies/
      cost    : ~/.config/codexbar/cost/
    """
    config_dir = config_path().parent
    cleared: List[str] = []

    if clear_all or cookies:
        cookie_dir = config_dir / "cookies"
        if cookie_dir.exists():
            import shutil
            shutil.rmtree(cookie_dir)
            cleared.append(str(cookie_dir))

    if clear_all or cost:
        cost_dir = config_dir / "cost"
        if cost_dir.exists():
            import shutil
            shutil.rmtree(cost_dir)
            cleared.append(str(cost_dir))

    if cleared:
        for p in cleared:
            click.echo(f"cleared: {p}")
    else:
        click.echo("nothing to clear.")


# --------------------------------------------------------------------------- #
#  main
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    cli()
