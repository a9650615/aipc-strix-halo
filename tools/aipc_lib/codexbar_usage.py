"""aipc usage — LiteLLM proxy DB summaries + CodexBar provider tracking.

Two data planes share this command group:

1. **LiteLLM proxy DB** (``list`` / ``aggregate`` / ``aliases``)
   Local SQLite spend from the LiteLLM gateway.

2. **CodexBar providers** (``show`` / ``cost`` / ``serve`` / ``gui`` / ``config``)
   Cross-tool rate windows via the ``dev-ai-codexbar-usage`` module
   (``codexbar_usage`` package / ``aipc-usage`` CLI).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import click
from rich.console import Console
from rich.table import Table

DEFAULT_DB_PATH = "/var/lib/litellm-proxy/litellm_proxy.db"

# ponytail: tools/aipc_lib → repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_USAGE_PKG = (
    _REPO_ROOT
    / "modules"
    / "dev-ai-codexbar-usage"
    / "files"
    / "usr"
    / "lib"
    / "aipc-codexbar-usage"
)
_GUI_PKG = (
    _REPO_ROOT
    / "modules"
    / "dev-ai-codexbar-gui"
    / "files"
    / "usr"
    / "lib"
    / "codexbar-gui"
)


@dataclass
class UsageRow:
    provider: str
    model: str
    total_tokens: int
    total_cost_usd: float
    request_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "request_count": self.request_count,
        }


_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "azure": "azure",
    "ollama": "ollama",
    "lemonade": "ollama",
    "vllm": "vllm",
    "qwen": "ollama",
    "gemini": "gemini",
}


def canonical_provider(alias: str) -> str | None:
    return _PROVIDER_ALIASES.get(alias.lower())


def _find_db(db_path: str | None = None) -> Path:
    path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
    if path.exists():
        return path
    alt = Path("/etc/aipc/litellm-proxy/db-path")
    if alt.exists():
        return Path(alt.read_text().strip())
    return path


def query_usage(db_path: str | None = None, provider: str | None = None) -> list[UsageRow]:
    """Return per-(provider, model) usage aggregates from the LiteLLM proxy DB."""
    path = _find_db(db_path)
    if not path.exists():
        return []

    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return []

    try:
        cur = conn.execute(
            """
            SELECT
                COALESCE(api_key, 'unknown') AS provider,
                COALESCE(model, 'unknown') AS model,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(spend), 0) AS total_cost_usd,
                COUNT(*) AS request_count
            FROM "LiteLLM_SpendLogs"
            GROUP BY 1, 2
            ORDER BY total_cost_usd DESC
            """
        )
        rows = [
            UsageRow(
                provider=str(r["provider"]),
                model=str(r["model"]),
                total_tokens=int(r["total_tokens"] or 0),
                total_cost_usd=float(r["total_cost_usd"] or 0),
                request_count=int(r["request_count"] or 0),
            )
            for r in cur.fetchall()
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    if provider:
        canon = canonical_provider(provider) or provider
        rows = [r for r in rows if r.provider == provider or r.provider == canon]
    return rows


def aggregate_by_provider(rows: list[UsageRow]) -> dict[str, dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        bucket = agg.setdefault(
            r.provider,
            {"total_tokens": 0, "total_cost_usd": 0.0, "request_count": 0, "models": 0},
        )
        bucket["total_tokens"] = int(bucket["total_tokens"]) + r.total_tokens
        bucket["total_cost_usd"] = float(bucket["total_cost_usd"]) + r.total_cost_usd
        bucket["request_count"] = int(bucket["request_count"]) + r.request_count
        bucket["models"] = int(bucket["models"]) + 1
    return agg


def ensure_codexbar_on_path() -> Optional[Path]:
    """Make ``codexbar_usage`` importable; return package root or None."""
    try:
        import codexbar_usage  # noqa: F401

        return Path(codexbar_usage.__file__).resolve().parent.parent  # type: ignore[name-defined]
    except ImportError:
        pass

    if _USAGE_PKG.is_dir():
        path = str(_USAGE_PKG)
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import codexbar_usage  # noqa: F401

            return _USAGE_PKG
        except ImportError:
            return None
    return None


def _run_aipc_usage(args: list[str]) -> int:
    """Invoke the codexbar CLI, preferring installed binary then module."""
    if shutil.which("aipc-usage"):
        proc = subprocess.run(["aipc-usage", *args], check=False)
        return proc.returncode

    pkg = ensure_codexbar_on_path()
    if pkg is None:
        click.echo(
            "codexbar usage package not found.\n"
            "Install module dev-ai-codexbar-usage (image) or:\n"
            f"  pip install -e {_USAGE_PKG}",
            err=True,
        )
        return 1

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{pkg}{os.pathsep}{env.get('PYTHONPATH', '')}"
    proc = subprocess.run(
        [sys.executable, "-m", "codexbar_usage", *args],
        env=env,
        check=False,
    )
    return proc.returncode


# --------------------------------------------------------------------------- #
# Click group — registered as `aipc usage`
# --------------------------------------------------------------------------- #


@click.group("usage")
def usage_cli() -> None:
    """Usage & cost: LiteLLM proxy DB + CodexBar provider windows."""


# --- LiteLLM plane --------------------------------------------------------- #


@usage_cli.command("list")
@click.option("--provider", default=None, help="Filter by provider alias.")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["table", "json"], case_sensitive=False),
    show_default=True,
)
@click.option("--db", "db_path", default=DEFAULT_DB_PATH, show_default=True)
def list_cmd(provider: str | None, fmt: str, db_path: str) -> None:
    """LiteLLM proxy: usage per (provider, model)."""
    rows = query_usage(db_path=db_path, provider=provider)
    if fmt == "json":
        click.echo(json.dumps({"rows": [r.to_dict() for r in rows]}, indent=2))
        return
    if not rows:
        click.echo("No LiteLLM usage data found.", err=True)
        return
    table = Table(title="aipc usage — LiteLLM per (provider, model)")
    for col in ("provider", "model", "requests", "tokens", "cost_usd"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r.provider,
            r.model,
            str(r.request_count),
            f"{r.total_tokens:,}",
            f"${r.total_cost_usd:.4f}",
        )
    Console().print(table)


@usage_cli.command("aggregate")
@click.option("--provider", default=None, help="Filter by provider alias.")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["table", "json"], case_sensitive=False),
    show_default=True,
)
@click.option("--db", "db_path", default=DEFAULT_DB_PATH, show_default=True)
def aggregate_cmd(provider: str | None, fmt: str, db_path: str) -> None:
    """LiteLLM proxy: usage aggregated by provider."""
    rows = query_usage(db_path=db_path, provider=provider)
    agg = aggregate_by_provider(rows)
    if fmt == "json":
        click.echo(json.dumps({"providers": agg}, indent=2))
        return
    if not agg:
        click.echo("No LiteLLM usage data found.", err=True)
        return
    table = Table(title="aipc usage — LiteLLM by provider")
    for col in ("provider", "models", "requests", "tokens", "cost_usd"):
        table.add_column(col)
    for name, data in sorted(agg.items()):
        table.add_row(
            name,
            str(data["models"]),
            str(data["request_count"]),
            f"{int(data['total_tokens']):,}",
            f"${data['total_cost_usd']:.4f}",
        )
    Console().print(table)


@usage_cli.command("aliases")
def aliases_cmd() -> None:
    """List LiteLLM provider aliases used by ``list`` / ``aggregate``."""
    table = Table(title="aipc usage — LiteLLM provider aliases")
    table.add_column("alias")
    table.add_column("canonical")
    for alias, canon in sorted(_PROVIDER_ALIASES.items()):
        table.add_row(alias, canon)
    Console().print(table)


# --- CodexBar plane -------------------------------------------------------- #


@usage_cli.command("show")
@click.option("--provider", "-p", default=None, help="Comma-separated provider ids.")
@click.option(
    "--format",
    "-f",
    "fmt",
    default="cards",
    type=click.Choice(["text", "json", "cards", "table"], case_sensitive=False),
    show_default=True,
)
@click.option(
    "--source",
    "-s",
    default="auto",
    type=click.Choice(["auto", "cli", "api", "web"], case_sensitive=False),
    show_default=True,
)
def show_cmd(provider: str | None, fmt: str, source: str) -> None:
    """CodexBar: show AI coding provider rate windows (Claude, Codex, …)."""
    args = ["usage", "--format", fmt, "--source", source]
    if provider:
        args.extend(["--provider", provider])
    sys.exit(_run_aipc_usage(args))


@usage_cli.command("cost")
@click.option("--days", "-d", default=30, show_default=True, type=int)
@click.option("--provider", "-p", default=None)
@click.option(
    "--group-by",
    type=click.Choice(["project", "model"], case_sensitive=False),
    default=None,
)
def cost_cmd(days: int, provider: str | None, group_by: str | None) -> None:
    """CodexBar: local Codex/Claude JSONL token cost scan."""
    args = ["cost", "--days", str(days)]
    if provider:
        args.extend(["--provider", provider])
    if group_by:
        args.extend(["--group-by", group_by])
    sys.exit(_run_aipc_usage(args))


@usage_cli.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", "-P", default=8080, show_default=True, type=int)
@click.option("--refresh-interval", default=60, show_default=True, type=int)
def serve_cmd(host: str, port: int, refresh_interval: int) -> None:
    """CodexBar: start localhost HTTP server (/health /usage /cost)."""
    sys.exit(
        _run_aipc_usage(
            [
                "serve",
                "--host",
                host,
                "--port",
                str(port),
                "--refresh-interval",
                str(refresh_interval),
            ]
        )
    )


@usage_cli.command("gui")
@click.option("--port", default=8080, show_default=True, type=int)
def gui_cmd(port: int) -> None:
    """CodexBar: launch the system-tray GUI (auto-starts usage server)."""
    if shutil.which("codexbar-gui"):
        sys.exit(subprocess.run(["codexbar-gui", str(port)], check=False).returncode)

    env = os.environ.copy()
    paths = []
    if _GUI_PKG.is_dir():
        paths.append(str(_GUI_PKG))
    if _USAGE_PKG.is_dir():
        paths.append(str(_USAGE_PKG))
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths + [env.get("PYTHONPATH", "")])

    try:
        sys.exit(
            subprocess.run(
                [sys.executable, "-m", "codexbar_gui", "--port", str(port)],
                env=env,
                check=False,
            ).returncode
        )
    except FileNotFoundError:
        click.echo(
            "codexbar-gui not found. Install module dev-ai-codexbar-gui or:\n"
            f"  pip install -e {_GUI_PKG}",
            err=True,
        )
        sys.exit(1)


@usage_cli.command("config")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def config_cmd(args: tuple[str, ...]) -> None:
    """CodexBar: forward to ``aipc-usage config …`` (enable/disable/set-api-key)."""
    sys.exit(_run_aipc_usage(["config", *args]))


@usage_cli.command("providers")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["table", "json"], case_sensitive=False),
    show_default=True,
)
def providers_cmd(fmt: str) -> None:
    """List CodexBar registry providers and which have a local fetcher."""
    if ensure_codexbar_on_path() is None:
        click.echo("codexbar usage package not importable", err=True)
        sys.exit(1)

    from codexbar_usage.providers import PROVIDER_MODULE_MAP
    from codexbar_usage.registry import all_providers

    rows = []
    for entry in all_providers():
        rows.append(
            {
                "id": entry.id,
                "name": entry.name,
                "auth": entry.auth_type,
                "source": entry.source_type,
                "linux": entry.linux,
                "fetcher": entry.id in PROVIDER_MODULE_MAP,
            }
        )

    if fmt == "json":
        click.echo(json.dumps({"providers": rows}, indent=2))
        return

    table = Table(title="aipc usage — CodexBar providers")
    for col in ("id", "name", "auth", "source", "linux", "fetcher"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["id"],
            r["name"],
            r["auth"],
            r["source"],
            r["linux"],
            "yes" if r["fetcher"] else "no",
        )
    Console().print(table)


def main() -> None:
    usage_cli()


if __name__ == "__main__":
    main()
