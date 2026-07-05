"""aipc-rag-browser --browser {firefox,chrome} — consent-gated history ingest.

Firefox and Chrome both keep history in a plain SQLite3 file (moz_places /
urls) — stdlib sqlite3 reads both, no extra dependency needed. The live
file is copied to a snapshot first since the running browser holds it
locked (SQLite WAL mode allows concurrent readers in practice, but a
snapshot avoids any lock contention entirely and is simplest).
"""

import argparse
import shutil
import sqlite3
import tempfile
from pathlib import Path

import yaml

from aipc_rag.common import chunk_text, get_logger, load_state, run_forever, save_state, upsert_chunks

CONSENT_CONFIG = Path("/etc/aipc/rag/browser-consent.yaml")
INTERVAL_S = 1800

BROWSER_PATHS = {
    "firefox": {
        "glob": str(Path.home() / ".mozilla/firefox/*.default*/places.sqlite"),
        "query": "SELECT url, title, COALESCE(title, url) FROM moz_places WHERE visit_count > 0",
    },
    "chrome": {
        "glob": str(Path.home() / ".config/google-chrome/Default/History"),
        "query": "SELECT url, title, COALESCE(title, url) FROM urls WHERE visit_count > 0",
    },
}

log = get_logger(__name__)


def has_consent(browser: str) -> bool:
    if not CONSENT_CONFIG.exists():
        return False
    data = yaml.safe_load(CONSENT_CONFIG.read_text()) or {}
    return bool(data.get(browser, {}).get("consent", False))


def find_db(browser: str) -> Path | None:
    import glob

    matches = glob.glob(BROWSER_PATHS[browser]["glob"])
    return Path(matches[0]) if matches else None


def read_history(browser: str, db_path: Path) -> dict[str, str]:
    """path key = url; value = 'title (url)' text to embed."""
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "snapshot.sqlite"
        shutil.copy2(db_path, snapshot)
        conn = sqlite3.connect(str(snapshot))
        try:
            rows = conn.execute(BROWSER_PATHS[browser]["query"]).fetchall()
        finally:
            conn.close()
    return {url: f"{title}\n{url}" for url, title, _ in rows}


def cycle(browser: str) -> None:
    if not has_consent(browser):
        log.info("no consent for %s, skipping cycle", browser)
        return

    db_path = find_db(browser)
    if db_path is None:
        log.info("no history db found for %s", browser)
        return

    source = f"browser-{browser}"
    state = load_state(source)
    current = read_history(browser, db_path)

    for url, text in current.items():
        if state.get(url) == text:
            continue
        upsert_chunks(source, url, chunk_text(text))

    save_state(source, current)
    log.info("%s: %d entries indexed", browser, len(current))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=list(BROWSER_PATHS), required=True)
    args = parser.parse_args()
    run_forever(INTERVAL_S, lambda: cycle(args.browser))


if __name__ == "__main__":
    main()
