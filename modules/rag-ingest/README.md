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

- Installs the Python watcher services via pip in `post-install.sh`.
- Enables desktop + code watchers by default.
- Leaves browser + screen-audio watchers disabled until the user opts in
  through the consent configs under `/etc/aipc/rag/`.

## Unit placement

The five `aipc-rag-*.service` units ship under `files/etc/systemd/system/`
and are placed by the renderer (bootc COPY / ansible copy into `/`).

## Dependencies

- `db-postgres` (vector store).
- `rag-embedder` (embedding + reranking endpoint).
