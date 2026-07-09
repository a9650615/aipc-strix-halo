"""Terminal UI rendering for provider usage data.

Supports three output modes matching CodexBar CLI output:
  - cards:   rich Panel grid with per-provider cards
  - table:   rich Table with provider | usage | reset | status
  - json:    pretty-printed JSON array
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.table import Table
from rich.text import Text

from codexbar_usage.config import load_config, resolve_api_key

_console = Console()


def _provider_display_name(provider_id: str) -> str:
    _DISPLAY = {
        "codex": "Codex",
        "openai": "OpenAI",
        "claude": "Claude",
        "gemini": "Gemini",
        "copilot": "GitHub Copilot",
        "cursor": "Cursor",
        "windsurf": "Windsurf",
        "zed": "Zed",
        "jetbrains": "JetBrains AI",
        "opencode": "OpenCode",
        "kiro": "Kiro",
        "augment": "Augment",
        "amp": "Amp",
        "zai": "z.ai",
        "deepseek": "DeepSeek",
        "moonshot": "Moonshot",
        "venice": "Venice",
        "openrouter": "OpenRouter",
        "groq": "GroqCloud",
        "elevenlabs": "ElevenLabs",
        "warp": "Warp",
        "poe": "Poe",
        "chutes": "Chutes",
        "codebuff": "Codebuff",
        "croft": "Croft",
        "alibaba": "Alibaba Coding",
        "alibabatokenplan": "Alibaba Token",
        "minimax": "MiniMax",
        "kimi": "Kimi",
        "kimik2": "Kimi K2",
        "kilo": "Kilo",
        "doubao": "Doubao",
        "synthetic": "Synthetic",
        "crossmodel": "CrossModel",
        "manus": "Manus",
        "llmproxy": "LLM Proxy",
        "litellm": "LiteLLM",
        "clawrouter": "ClawRouter",
        "deepgram": "Deepgram",
        "azureopenai": "Azure OpenAI",
        "bedrock": "AWS Bedrock",
        "vertexai": "Vertex AI",
        "antigravity": "Antigravity",
        "ollama": "Ollama",
        "perplexity": "Perplexity",
        "mistral": "Mistral",
        "abacus": "Abacus AI",
        "sakana": "Sakana AI",
        "stepfun": "StepFun",
        "qoder": "Qoder",
        "devin": "Devin",
        "commandcode": "Command Code",
        "t3chat": "T3 Chat",
        "mimo": "MiMo",
        "factory": "Factory",
        "opencodego": "OpenCode Go",
    }
    return _DISPLAY.get(provider_id, provider_id.title())


def _status_for_provider(provider_id: str) -> str:
    """Determine provider status based on API key availability."""
    api_key = resolve_api_key(provider_id)
    if api_key:
        return "configured"
    return "no-api-key"


def _usage_bar(used_pct: float) -> str:
    """Render a usage bar using rich Progress."""
    clamped = min(max(used_pct, 0.0), 1.0)
    if clamped >= 1.0:
        return "[red]████████████████████[/red] 100%"
    width = int(clamped * 20)
    bar = "█" * width + "░" * (20 - width)
    if clamped > 0.8:
        color = "red"
    elif clamped > 0.5:
        color = "yellow"
    else:
        color = "green"
    return f"[{color}]{bar}[/{color}] {clamped * 100:.0f}%"


def render_card(provider_id: str, snapshot: Dict[str, Any]) -> Panel:
    display = _provider_display_name(provider_id)
    status = snapshot.get("status", _status_for_provider(provider_id))
    primary = snapshot.get("primary") or {}
    used_pct = primary.get("used_percent", 0)
    reset_desc = primary.get("reset_description") or primary.get("resets_in", "")
    window_min = primary.get("window_minutes")
    account = snapshot.get("identity", {}).get("account_email", "")

    lines: List[Any] = []
    lines.append(f"[bold]{display}[/bold]")
    if account:
        lines.append(f"[dim]Account: {account}[/dim]")
    lines.append("")
    lines.append(f"Usage: {_usage_bar(used_pct)}")
    if window_min:
        lines.append(f"Window: {window_min} min")
    if reset_desc:
        lines.append(f"Resets: [cyan]{reset_desc}[/cyan]")
    lines.append("")
    lines.append(f"Status: [{_status_color(status)}]{status}[/{_status_color(status)}]")

    secondary = snapshot.get("secondary")
    if secondary:
        lines.append("")
        sec_pct = secondary.get("used_percent", 0)
        sec_desc = secondary.get("reset_description", "")
        lines.append(f"Secondary: {_usage_bar(sec_pct)}")
        if sec_desc:
            lines.append(f"  Resets: [dim]{sec_desc}[/dim]")

    extra = snapshot.get("extra_rate_windows")
    if extra:
        lines.append("")
        for i, rw in enumerate(extra):
            ep = rw.get("used_percent", 0)
            ed = rw.get("reset_description", "")
            label = rw.get("label", f"Window {i + 1}")
            lines.append(f"{label}: {_usage_bar(ep)}")
            if ed:
                lines.append(f"  [dim]{ed}[/dim]")

    cost = snapshot.get("provider_cost")
    if cost:
        lines.append("")
        lines.append(f"Cost: [green]${cost.get('total', 0):.4f}[/green]")

    text = Text.from_markup("\n".join(str(l) for l in lines))
    border = _status_border(status)
    return Panel(text, title=f"[bold]{display}[/bold]", border_style=border)


def _status_color(status: str) -> str:
    if status == "configured":
        return "green"
    if status in ("error", "failed"):
        return "red"
    if status == "no-api-key":
        return "yellow"
    return "white"


def _status_border(status: str) -> str:
    if status == "configured":
        return "green"
    if status in ("error", "failed"):
        return "red"
    return "dim"


def render_cards(results: List[Dict[str, Any]]) -> None:
    for r in results:
        panel = render_card(r["provider"], r["snapshot"])
        _console.print(panel)
        _console.print()


def render_table(results: List[Dict[str, Any]]) -> None:
    table = Table(title="aipc usage")
    table.add_column("Provider", style="bold")
    table.add_column("Usage", no_wrap=True)
    table.add_column("Reset", style="cyan")
    table.add_column("Status")

    for r in results:
        provider_id = r["provider"]
        display = _provider_display_name(provider_id)
        snapshot = r["snapshot"]
        primary = snapshot.get("primary") or {}
        used_pct = primary.get("used_percent", 0)
        bar = _usage_bar(used_pct)
        reset_desc = primary.get("reset_description") or "-"
        status = snapshot.get("status", _status_for_provider(provider_id))
        table.add_row(display, bar, reset_desc, status)

    _console.print(table)


def render_json(results: List[Dict[str, Any]], sort_providers: bool = True) -> None:
    if sort_providers:
        results = sorted(results, key=lambda r: r["provider"])
    output = []
    for r in results:
        entry = {
            "provider": r["provider"],
            "display_name": _provider_display_name(r["provider"]),
            "snapshot": r["snapshot"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        output.append(entry)
    print(json.dumps(output, indent=2, ensure_ascii=False))


def render_cost_table(results: List[Dict[str, Any]]) -> None:
    table = Table(title="aipc usage cost")
    table.add_column("Provider", style="bold")
    table.add_column("Total Cost (USD)", justify="right")
    table.add_column("Period", style="dim")
    table.add_column("Status")

    for r in results:
        provider_id = r["provider"]
        display = _provider_display_name(provider_id)
        cost = r["snapshot"].get("provider_cost", {})
        total = cost.get("total", 0)
        period = cost.get("period", "-")
        status = r["snapshot"].get("status", _status_for_provider(provider_id))
        table.add_row(
            display,
            f"${total:.4f}",
            str(period),
            status,
        )
    _console.print(table)


def render_cards_brief(results: List[Dict[str, Any]]) -> None:
    """Compact card view — icon, name, usage bar, status on one line each."""
    for r in results:
        provider_id = r["provider"]
        display = _provider_display_name(provider_id)
        snapshot = r["snapshot"]
        primary = snapshot.get("primary") or {}
        used_pct = primary.get("used_percent", 0)
        status = snapshot.get("status", _status_for_provider(provider_id))
        sc = _status_color(status)
        bar = _usage_bar(used_pct)
        _console.print(f"  [{sc}]{display}[/{sc}] {bar}  {status}")
