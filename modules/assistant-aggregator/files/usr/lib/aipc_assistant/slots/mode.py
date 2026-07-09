from __future__ import annotations

from pathlib import Path

from aipc_assistant.paths import mode_path

VALID = frozenset({"local", "online"})


def get_mode(path: Path | None = None) -> str:
    p = path or mode_path()
    if not p.is_file():
        return "local"
    raw = p.read_text(encoding="utf-8").strip().lower()
    return raw if raw in VALID else "local"


def set_mode(mode: str, path: Path | None = None) -> str:
    m = mode.strip().lower()
    if m not in VALID:
        raise ValueError(f"mode must be local|online, got {mode!r}")
    p = path or mode_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(m + "\n", encoding="utf-8")
    return m
