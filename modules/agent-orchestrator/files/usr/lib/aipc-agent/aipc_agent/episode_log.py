"""Append-only episode log for self-improvement / doctor."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DIR = Path(os.environ.get("AIPC_EPISODE_DIR", "/var/lib/aipc-agent/episodes"))
_MAX_BYTES = int(os.environ.get("AIPC_EPISODE_MAX_BYTES", str(8 * 1024 * 1024)))


def _path() -> Path:
    day = time.strftime("%Y-%m-%d")
    return _DIR / f"episodes-{day}.jsonl"


def append(event: dict[str, Any]) -> None:
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        row = dict(event)
        row.setdefault("ts", time.time())
        line = json.dumps(row, ensure_ascii=False) + "\n"
        p = _path()
        with _LOCK:
            if p.is_file() and p.stat().st_size > _MAX_BYTES:
                # rotate
                bak = p.with_suffix(".jsonl.1")
                try:
                    p.replace(bak)
                except OSError:
                    pass
            with p.open("a", encoding="utf-8") as f:
                f.write(line)
    except OSError as exc:
        print(f"aipc-agent: episode log fail: {exc}", flush=True)


def last_path() -> Path | None:
    if not _DIR.is_dir():
        return None
    files = sorted(_DIR.glob("episodes-*.jsonl"), reverse=True)
    return files[0] if files else None
