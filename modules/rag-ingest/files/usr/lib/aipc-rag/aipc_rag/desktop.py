"""aipc-rag-desktop — watches ~/Desktop and ~/Documents.

Text-ish files only for v1 (plain text, markdown, common code extensions).
PDF/DOCX would need an extra parsing dependency — not pulled in until a
real need shows up (ponytail: YAGNI).
"""

import os
from pathlib import Path

from aipc_rag.common import chunk_text, delete_path, get_logger, load_state, run_forever, save_state, upsert_chunks

SOURCE = "desktop"
WATCH_DIRS = [Path.home() / "Desktop", Path.home() / "Documents"]
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".org", ".py", ".js", ".ts", ".sh", ".json", ".yaml", ".yml"}
INTERVAL_S = 300

log = get_logger(__name__)


def scan() -> dict[str, float]:
    found = {}
    for base in WATCH_DIRS:
        if not base.is_dir():
            continue
        for root, _dirs, files in os.walk(base):
            for name in files:
                p = Path(root) / name
                if p.suffix.lower() in TEXT_EXTENSIONS:
                    try:
                        found[str(p)] = p.stat().st_mtime
                    except OSError:
                        continue
    return found


def cycle() -> None:
    state = load_state(SOURCE)
    current = scan()

    for path, mtime in current.items():
        if state.get(path) == mtime:
            continue
        try:
            text = Path(path).read_text(errors="ignore")
        except OSError:
            continue
        upsert_chunks(SOURCE, path, chunk_text(text))
        log.info("indexed %s", path)

    for path in set(state) - set(current):
        delete_path(SOURCE, path)
        log.info("removed %s", path)

    save_state(SOURCE, current)


def main() -> None:
    run_forever(INTERVAL_S, cycle)


if __name__ == "__main__":
    main()
