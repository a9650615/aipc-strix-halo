"""aipc-rag-code — watches repos listed in ~/.config/aipc/rag/repos.yaml.

Line-window chunking for v1 (per proposal: smarter AST-aware chunking is
Q3, deferred). Default repo list is empty — a no-op until the user adds
paths.
"""

import os
from pathlib import Path

import yaml

from aipc_rag.common import delete_path, get_logger, load_state, run_forever, save_state, upsert_chunks

SOURCE = "code"
REPOS_CONFIG = Path.home() / ".config/aipc/rag/repos.yaml"
INTERVAL_S = 600
LINES_PER_CHUNK = 200
LINES_OVERLAP = 20
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

log = get_logger(__name__)


def load_repos() -> list[str]:
    if not REPOS_CONFIG.exists():
        return []
    data = yaml.safe_load(REPOS_CONFIG.read_text()) or {}
    return data.get("repos", []) or []


def chunk_lines(lines: list[str]) -> list[str]:
    if len(lines) <= LINES_PER_CHUNK:
        return ["".join(lines)] if lines else []
    chunks = []
    start = 0
    while start < len(lines):
        end = start + LINES_PER_CHUNK
        chunks.append("".join(lines[start:end]))
        if end >= len(lines):
            break
        start = end - LINES_OVERLAP
    return chunks


def scan(repos: list[str]) -> dict[str, float]:
    found = {}
    for repo in repos:
        base = Path(repo)
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                p = Path(root) / name
                try:
                    found[str(p)] = p.stat().st_mtime
                except OSError:
                    continue
    return found


def cycle() -> None:
    repos = load_repos()
    if not repos:
        return

    state = load_state(SOURCE)
    current = scan(repos)

    for path, mtime in current.items():
        if state.get(path) == mtime:
            continue
        try:
            lines = Path(path).read_text(errors="ignore").splitlines(keepends=True)
        except OSError:
            continue
        upsert_chunks(SOURCE, path, chunk_lines(lines))
        log.info("indexed %s", path)

    for path in set(state) - set(current):
        delete_path(SOURCE, path)
        log.info("removed %s", path)

    save_state(SOURCE, current)


def main() -> None:
    run_forever(INTERVAL_S, cycle)


if __name__ == "__main__":
    main()
