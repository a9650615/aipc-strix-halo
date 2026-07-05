"""Shared helpers for the four rag-ingest watchers.

openspec/changes/phase-2-memory tasks 5.1-5.4 — poll a source, diff
against a small on-disk state cache, chunk changed content, embed via
rag-embedder, upsert into Postgres/pgvector's rag_chunks table.
"""

import json
import logging
import time
from pathlib import Path

import psycopg2
import requests

EMBEDDER_URL = "http://127.0.0.1:8201/embed"
PG_DSN = "postgresql://postgres@127.0.0.1:5432/aipc"
STATE_DIR = Path("/var/lib/aipc-rag/state")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def load_state(source: str) -> dict:
    """path -> mtime cache for a source, so a poll cycle only touches changed files."""
    f = STATE_DIR / f"{source}.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text())


def save_state(source: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = STATE_DIR / f"{source}.json"
    f.write_text(json.dumps(state))


def chunk_text(text: str, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    """Sliding-window chunker. Good enough for v1; swap for a smarter
    (sentence/token-aware) splitter if retrieval quality demands it."""
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if c.strip()]


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = requests.post(EMBEDDER_URL, json={"texts": texts}, timeout=30)
    resp.raise_for_status()
    return resp.json()["embeddings"]


def upsert_chunks(source: str, path: str, chunks: list[str]) -> None:
    if not chunks:
        return
    vectors = embed(chunks)
    with psycopg2.connect(PG_DSN) as conn, conn.cursor() as cur:
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            cur.execute(
                """
                INSERT INTO rag_chunks (source, path, chunk_index, content, embedding, updated_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (source, path, chunk_index)
                DO UPDATE SET content = EXCLUDED.content,
                              embedding = EXCLUDED.embedding,
                              updated_at = now()
                """,
                (source, path, idx, chunk, list(vector)),
            )
        conn.commit()


def delete_path(source: str, path: str) -> None:
    with psycopg2.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM rag_chunks WHERE source = %s AND path = %s", (source, path))
        conn.commit()


def run_forever(interval_s: int, cycle_fn) -> None:
    """ponytail: no signal-driven reload/backoff — a fixed-interval loop is
    the simplest thing that works for a v1 desktop-scale watcher. Add
    backoff-on-error or inotify-driven triggering if polling cost or
    staleness ever actually matters."""
    log = get_logger(cycle_fn.__module__)
    while True:
        try:
            cycle_fn()
        except Exception:
            log.exception("cycle failed, will retry next interval")
        time.sleep(interval_s)
