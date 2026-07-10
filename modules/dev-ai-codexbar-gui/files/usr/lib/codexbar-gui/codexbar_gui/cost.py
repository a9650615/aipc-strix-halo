"""Official ``codexbar cost`` adapter (local spend / token history)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, List, Optional

from codexbar_gui.upstream import find_codexbar_binary

logger = logging.getLogger("codexbar_gui.cost")

COST_TIMEOUT = float(os.environ.get("CODEXBAR_COST_TIMEOUT", "45"))


@dataclass
class DailyCost:
    date: str
    total_cost: float
    total_tokens: int


@dataclass
class CostView:
    provider: str
    currency: str = "USD"
    source: str = ""
    history_days: int = 30
    today_cost: float = 0.0
    today_tokens: int = 0
    period_cost: float = 0.0
    period_tokens: int = 0
    daily: List[DailyCost] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def today_line(self) -> str:
        return (
            f"Today: ${self.today_cost:,.2f} · {_fmt_tokens(self.today_tokens)} tokens"
        )

    @property
    def period_line(self) -> str:
        return (
            f"Last {self.history_days} days: ${self.period_cost:,.2f} · "
            f"{_fmt_tokens(self.period_tokens)} tokens"
        )


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def parse_cost_item(item: dict[str, Any]) -> CostView:
    provider = str(item.get("provider") or "unknown")
    daily_raw = item.get("daily") if isinstance(item.get("daily"), list) else []
    days: List[DailyCost] = []
    for row in daily_raw:
        if not isinstance(row, dict):
            continue
        try:
            cost = float(row.get("totalCost") or row.get("total_cost") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        try:
            tokens = int(row.get("totalTokens") or row.get("total_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        d = str(row.get("date") or "")
        if not d:
            continue
        days.append(DailyCost(date=d, total_cost=cost, total_tokens=tokens))
    days.sort(key=lambda x: x.date)
    period_cost = sum(d.total_cost for d in days)
    period_tokens = sum(d.total_tokens for d in days)
    today = date.today().isoformat()
    today_row = next((d for d in reversed(days) if d.date == today), None)
    if today_row is None and days:
        # use last day as "latest"
        today_row = days[-1]
    try:
        hist = int(item.get("historyDays") or item.get("history_days") or 30)
    except (TypeError, ValueError):
        hist = 30
    return CostView(
        provider=provider,
        currency=str(item.get("currencyCode") or item.get("currency") or "USD"),
        source=str(item.get("source") or ""),
        history_days=hist,
        today_cost=today_row.total_cost if today_row else 0.0,
        today_tokens=today_row.total_tokens if today_row else 0,
        period_cost=period_cost,
        period_tokens=period_tokens,
        daily=days,
    )


def fetch_cost(
    provider: str = "claude",
    days: int = 30,
    timeout: float = COST_TIMEOUT,
) -> Optional[CostView]:
    binary = find_codexbar_binary()
    if not binary:
        return None
    cmd = [
        binary,
        "cost",
        "--provider",
        provider,
        "--days",
        str(max(1, min(365, days))),
        "--format",
        "json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("cost CLI failed: %s", exc)
        return CostView(provider=provider, error=str(exc))
    text = (proc.stdout or "").strip()
    if not text:
        return CostView(
            provider=provider,
            error=(proc.stderr or "empty cost output")[:200],
        )
    start = text.find("[")
    if start < 0:
        start = text.find("{")
    if start < 0:
        return CostView(provider=provider, error="no JSON in cost output")
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError as exc:
        return CostView(provider=provider, error=str(exc))
    if isinstance(data, list):
        if not data:
            return CostView(provider=provider, error="no cost data")
        item = data[0] if isinstance(data[0], dict) else {}
    elif isinstance(data, dict):
        item = data
    else:
        return CostView(provider=provider, error="unexpected cost shape")
    return parse_cost_item(item)
