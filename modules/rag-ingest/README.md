# rag-ingest

Four RAG watcher services that keep the local vector index fresh:

| Service | Watches | Default |
|---|---|---|
| `aipc-rag-desktop` | `~/Desktop`, `~/Documents` | enabled |
| `aipc-rag-code` | repos listed in `~/.config/aipc/rag/repos.yaml` | enabled |
| `aipc-rag-browser-firefox` | Firefox `places.sqlite` | disabled (consent-gated) |
| `aipc-rag-browser-chrome` | Chrome `History` | disabled (consent-gated) |
| `aipc-rag-screen-audio` | OCR frames + audio transcript | disabled (consent-gated) |

## Design decisions

- **D3** — four RAG sources (Desktop, Code, Browser, Screen+Audio).
- **D6** — browser ingest is consent-gated; the default
  `/etc/aipc/rag/browser-consent.yaml` sets `consent: false` for every
  browser.
- **D7** — screen+audio capture is opt-in and has a TTL (`ttl_days: 7`
  default).

## What it does

- Ships `aipc_rag`, a small Python package
  (`files/usr/lib/aipc-rag/aipc_rag/`: `common.py` + one module per
  watcher) installed into its own venv at `/usr/lib/aipc-rag/venv` —
  same pattern as `agent-orchestrator`.
- Each watcher polls its source on a fixed interval, diffs against a
  small per-source JSON state cache under `/var/lib/aipc-rag/state/`,
  chunks changed content, calls `rag-embedder`'s `/embed`, and
  upserts into `db-postgres`'s `rag_chunks` table.
- Enables desktop + code watchers by default; leaves browser +
  screen-audio disabled until the user opts in via the consent
  configs under `/etc/aipc/rag/`.
- `screen-audio` is real for consent/TTL-purge/pause-on-mute, but the
  actual OCR + audio-transcript capture is a documented stub — see
  `aipc_rag/screen_audio.py`'s docstring for why (Phase 3 dependency,
  OCR model choice not yet made).

## Unit placement

The five `aipc-rag-*.service` units ship under `files/etc/systemd/system/`
and are placed by the renderer (bootc COPY / ansible copy into `/`).

## Dependencies

- `db-postgres` (vector store — needs its `rag_chunks` table, see
  `db-postgres/files/usr/lib/aipc/init-pgvector.sql`).
- `rag-embedder` (embedding endpoint at `127.0.0.1:8201/embed`; the
  backing image itself has no source in this repo yet, see that
  module's README).
