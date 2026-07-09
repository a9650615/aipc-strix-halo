"""Local JSONL cost scanners for Codex and Claude CLI sessions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProjectCost:
    name: str
    tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class CostSnapshot:
    session_tokens: int = 0
    session_cost_usd: float = 0.0
    last_30_days_tokens: int = 0
    last_30_days_cost_usd: float = 0.0
    projects: List[ProjectCost] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_tokens": self.session_tokens,
            "session_cost_usd": self.session_cost_usd,
            "last_30_days_tokens": self.last_30_days_tokens,
            "last_30_days_cost_usd": self.last_30_days_cost_usd,
            "projects": [
                {"name": p.name, "tokens": p.tokens, "cost_usd": p.cost_usd}
                for p in self.projects
            ],
        }


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _tokens_from_usage(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "total_tokens",
    ):
        val = usage.get(key)
        if isinstance(val, (int, float)):
            if key == "total_tokens":
                return int(val)
            total += int(val)
    return total


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("could not read %s: %s", path, exc)
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _scan_jsonl_files(
    files: Iterable[Path],
    now: datetime,
    history_days: int,
) -> CostSnapshot:
    cutoff = now - timedelta(days=history_days)
    project_map: dict[str, ProjectCost] = {}
    session_tokens = 0
    session_cost = 0.0
    window_tokens = 0
    window_cost = 0.0

    for path in files:
        for row in _iter_jsonl(path):
            ts = _parse_ts(row.get("timestamp") or row.get("ts"))
            usage = row.get("usage") or {}
            tokens = _tokens_from_usage(usage)
            cost = row.get("cost_usd")
            if cost is None:
                cost = row.get("cost")
            try:
                cost_f = float(cost) if cost is not None else 0.0
            except (TypeError, ValueError):
                cost_f = 0.0

            project = (
                row.get("cwd")
                or row.get("project")
                or row.get("project_path")
                or path.stem
            )
            project = str(project)

            # Count everything in the file as "session" aggregate for the
            # scanned tree (matches upstream CLI card totals).
            session_tokens += tokens
            session_cost += cost_f

            if ts is None or ts >= cutoff:
                window_tokens += tokens
                window_cost += cost_f
                pc = project_map.get(project)
                if pc is None:
                    pc = ProjectCost(name=project)
                    project_map[project] = pc
                pc.tokens += tokens
                pc.cost_usd += cost_f

    projects = sorted(project_map.values(), key=lambda p: (-p.cost_usd, p.name))
    return CostSnapshot(
        session_tokens=session_tokens,
        session_cost_usd=session_cost,
        last_30_days_tokens=window_tokens,
        last_30_days_cost_usd=window_cost,
        projects=projects,
    )


def _codex_jsonl_files(base: Path) -> List[Path]:
    roots = [
        base / ".codex" / "sessions",
        base / ".codex" / "logs",
    ]
    files: List[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.jsonl")))
    return files


def _claude_jsonl_files(base: Path) -> List[Path]:
    roots = [
        base / ".claude" / "projects",
        base / ".claude" / "sessions",
    ]
    files: List[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.jsonl")))
    return files


def load_token_costs(
    provider_id: str,
    base_path: Optional[Path] = None,
    now: Optional[datetime] = None,
    history_days: int = 30,
) -> CostSnapshot:
    """Scan local JSONL logs and return aggregated token/cost totals."""
    base = Path(base_path) if base_path is not None else Path.home()
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    pid = provider_id.lower()
    if pid in {"codex", "openai-codex", "openai_codex"}:
        files = _codex_jsonl_files(base)
    elif pid in {"claude", "anthropic"}:
        files = _claude_jsonl_files(base)
    else:
        return CostSnapshot()

    return _scan_jsonl_files(files, when, history_days)


def cost_results_for_cli(
    days: int = 30,
    provider: Optional[str] = None,
    base_path: Optional[Path] = None,
) -> List[dict[str, Any]]:
    """Build the ``{provider, snapshot}`` list used by ``aipc-usage cost``."""
    ids = ["codex", "claude"] if not provider else [provider]
    now = datetime.now(timezone.utc)
    out: List[dict[str, Any]] = []
    for pid in ids:
        snap = load_token_costs(
            provider_id=pid,
            base_path=base_path,
            now=now,
            history_days=days,
        )
        if snap.session_tokens == 0 and snap.session_cost_usd == 0.0 and not snap.projects:
            continue
        out.append(
            {
                "provider": pid,
                "snapshot": {
                    "status": "ok",
                    "provider_cost": {
                        "total": snap.session_cost_usd,
                        "tokens": snap.session_tokens,
                        "period": f"{days}d",
                        "last_30_days_tokens": snap.last_30_days_tokens,
                        "last_30_days_cost_usd": snap.last_30_days_cost_usd,
                        "projects": [
                            {"name": p.name, "tokens": p.tokens, "cost_usd": p.cost_usd}
                            for p in snap.projects
                        ],
                    },
                    "identity": {},
                },
            }
        )
    return out
