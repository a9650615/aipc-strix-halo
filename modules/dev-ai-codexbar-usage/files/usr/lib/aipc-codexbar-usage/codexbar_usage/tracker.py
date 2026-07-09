"""Database query helpers for the LiteLLM proxy SQLite database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "/var/lib/litellm-proxy/litellm_proxy.db"


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


def _find_db(db_path: str | None = None) -> Path:
    path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
    if path.exists():
        return path
    alt = Path("/etc/aipc/litellm-proxy/db-path")
    if alt.exists():
        return Path(alt.read_text().strip())
    raise FileNotFoundError(f"LiteLLM proxy DB not found at {DEFAULT_DB_PATH}")


def query_usage(db_path: str | None = None, provider: str | None = None) -> list[UsageRow]:
    """Return per-(provider, model) usage aggregates from the LiteLLM proxy DB.

    Reads from the `litellm_proxy_db.api_call` table (the standard schema
    shipped with litellm[major]). When no rows are found or the DB is
    empty/missing, returns an empty list rather than raising — the CLI
    should still produce valid output.
    """
    try:
        path = _find_db(db_path)
    except FileNotFoundError:
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
                model,
                SUM(tokens_used) AS total_tokens,
                COALESCE(SUM(cost_in_usd), 0) AS total_cost_usd,
                COUNT(*) AS request_count
            FROM api_call
            GROUP BY provider, model
            ORDER BY total_cost_usd DESC
            """,
        )
        rows: list[UsageRow] = []
        for row in cur:
            provider_val = row["provider"]
            if provider and provider_val != provider:
                continue
            rows.append(UsageRow(
                provider=provider_val,
                model=row["model"] or "unknown",
                total_tokens=row["total_tokens"] or 0,
                total_cost_usd=row["total_cost_usd"] or 0.0,
                request_count=row["request_count"] or 0,
            ))
        return rows
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def aggregate_by_provider(rows: list[UsageRow]) -> dict[str, dict[str, int | float]]:
    """Collapse per-(provider, model) rows into per-provider aggregates."""
    agg: dict[str, dict[str, int | float]] = {}
    for r in rows:
        bucket = agg.setdefault(r.provider, {
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "request_count": 0,
            "models": 0,
        })
        bucket["total_tokens"] = int(bucket["total_tokens"]) + r.total_tokens
        bucket["total_cost_usd"] = float(bucket["total_cost_usd"]) + r.total_cost_usd
        bucket["request_count"] = int(bucket["request_count"]) + r.request_count
        bucket["models"] = int(bucket["models"]) + 1
    return agg
