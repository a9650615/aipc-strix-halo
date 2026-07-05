from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

PG_DSN = "postgresql://postgres@127.0.0.1:5432/aipc"
STATE_DIR = Path("/var/lib/aipc-rag/state")
BROWSER_CONSENT = Path("/etc/aipc/rag/browser-consent.yaml")
SCREEN_AUDIO_CONFIG = Path("/etc/aipc/rag/screen-audio.yaml")


@dataclass
class Source:
    name: str
    service: str
    default_enabled: bool


# openspec/changes/phase-2-memory#7.1 — the canonical source list.
SOURCES: list[Source] = [
    Source("desktop", "aipc-rag-desktop.service", True),
    Source("code", "aipc-rag-code.service", True),
    Source("browser-firefox", "aipc-rag-browser-firefox.service", False),
    Source("browser-chrome", "aipc-rag-browser-chrome.service", False),
    Source("screen-audio", "aipc-rag-screen-audio.service", False),
]

_BY_NAME = {s.name: s for s in SOURCES}


def find_source(name: str) -> Source:
    if name not in _BY_NAME:
        raise KeyError(f"unknown source {name!r} (see `aipc rag list-sources`)")
    return _BY_NAME[name]


def service_is_active(
    service: str, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> bool:
    proc = runner(["systemctl", "is-active", "--quiet", service], check=False)
    return proc.returncode == 0


def default_pg_query(sql: str, params: tuple = ()) -> list[tuple]:
    import psycopg2

    with psycopg2.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except psycopg2.ProgrammingError:
            return []


QueryFn = Callable[[str, tuple], list[tuple]]


def source_status(
    source: Source,
    query_fn: QueryFn = default_pg_query,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """item count + vector count (same number, one row per chunk) + last
    updated_at, from rag_chunks. Empty/zero if Postgres isn't reachable —
    callers running without hardware still get a usable (if empty) table."""
    try:
        rows = query_fn(
            "SELECT count(*), max(updated_at) FROM rag_chunks WHERE source = %s", (source.name,)
        )
        count, last_cycle = rows[0] if rows else (0, None)
    except Exception:
        count, last_cycle = 0, None
    return {
        "source": source.name,
        "active": service_is_active(source.service, runner=runner),
        "vector_count": count,
        "last_cycle": last_cycle,
    }


def _consent_gate(source: Source) -> tuple[Path, str] | None:
    """(config path, key) for sources gated by a consent file, else None."""
    if source.name.startswith("browser-"):
        return BROWSER_CONSENT, source.name.removeprefix("browser-")
    if source.name == "screen-audio":
        return SCREEN_AUDIO_CONFIG, "enabled"
    return None


def _write_consent(path: Path, key: str, value: bool) -> None:
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    data = data or {}
    if path is BROWSER_CONSENT:
        data.setdefault(key, {})["consent"] = value
    else:
        data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def enable_source(
    source: Source, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> None:
    gate = _consent_gate(source)
    if gate is not None:
        _write_consent(*gate, True)
    runner(["sudo", "systemctl", "enable", "--now", source.service], check=True)


def disable_source(
    source: Source, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> None:
    gate = _consent_gate(source)
    if gate is not None:
        _write_consent(*gate, False)
    runner(["sudo", "systemctl", "disable", "--now", source.service], check=True)


def reindex_source(
    source: Source,
    query_fn: QueryFn = default_pg_query,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Drop this source's vectors + state cache, then restart its watcher
    so the next poll cycle treats every file as new."""
    query_fn("DELETE FROM rag_chunks WHERE source = %s", (source.name,))
    state_file = STATE_DIR / f"{source.name}.json"
    state_file.unlink(missing_ok=True)
    runner(["sudo", "systemctl", "restart", source.service], check=True)


def purge_source(source: Source, query_fn: QueryFn = default_pg_query) -> int:
    """Drop this source's vectors + state cache. Returns rows deleted.
    Does NOT touch the service or consent — see `aipc rag disable` for that."""
    rows = query_fn("DELETE FROM rag_chunks WHERE source = %s RETURNING id", (source.name,))
    state_file = STATE_DIR / f"{source.name}.json"
    state_file.unlink(missing_ok=True)
    return len(rows)
