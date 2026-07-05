# Memory + RAG (Phase 2)

Status as of 2026-07-06: all 5 modules scaffolded and `.disabled`, most
build-time bugs fixed, real logic written for 3 of 4 ingest watchers.
Nothing in this capability is hardware-verified yet — see
`openspec/changes/phase-2-memory/tasks.md` for the authoritative per-task
state. This doc describes what's actually built, not the aspirational
end-state.

## End-to-end flow

```
                 ┌──────────────┐
  ~/Desktop  ───▶│              │
  ~/Documents ──▶│ aipc-rag-*   │  poll, diff (mtime cache in
  repos.yaml ───▶│  watchers    │  /var/lib/aipc-rag/state/*.json),
  places.sqlite─▶│ (rag-ingest) │  chunk changed content
  History    ───▶│              │
                 └──────┬───────┘
                        │ POST /embed
                        ▼
                 ┌──────────────┐
                 │ rag-embedder │  bge-m3 (+ bge-reranker-v2-m3)
                 │  :8201       │  — image itself not built yet
                 └──────┬───────┘
                        │ vectors
                        ▼
                 ┌──────────────┐
                 │  db-postgres │  rag_chunks table (pgvector,
                 │  :5432       │  UNIQUE(source, path, chunk_index))
                 └──────────────┘
                        ▲
                        │ metadata + facts
                 ┌──────┴───────┐
                 │ memory-mem0  │  across-session recall for Phase 4
                 │  :7000       │  agents, via LiteLLM for its own
                 └──────────────┘  summarisation calls
```

`embed-bge` is also registered as a LiteLLM alias
(`modules/llm-litellm/files/etc/aipc/litellm/config.yaml`) for any
caller that prefers going through the gateway instead of hitting
rag-embedder directly.

## Consent gates

| Source | Default | Gate file |
|---|---|---|
| Desktop + Documents | on | none |
| Code repos | on (empty repo list = no-op) | `~/.config/aipc/rag/repos.yaml` |
| Firefox / Chrome history | off | `/etc/aipc/rag/browser-consent.yaml` |
| Screen OCR + audio transcript | off | `/etc/aipc/rag/screen-audio.yaml` (`ttl_days`) |

`aipc rag enable <source>` / `disable <source>` write these files and
toggle the corresponding systemd unit in one step (see `tools/aipc_lib/rag.py`).

## Backend + migration path

`pgvector` (inside `db-postgres`) is the default and only wired backend.
`db-qdrant` ships `.disabled` — `aipc doctor` warns once `rag_chunks`
crosses ~1M rows (`check_vector_count` in `tools/aipc_lib/doctor.py`),
suggesting `aipc db migrate qdrant`. That migration command itself is
**not implemented** — only documented as the intended path
(`modules/db-qdrant/README.md`); building it is future work once a real
corpus actually approaches that size.

## Known gaps (not guessed around, tracked instead)

- **rag-embedder has no backing image.** `docker.io/aipc/rag-embedder:latest`
  is a placeholder reference; nothing in this repo builds it. Needs a
  serving-framework choice (TEI / vLLM / custom FastAPI) before it can
  run — see `modules/rag-embedder/README.md`.
- **Screen+audio capture is a stub.** Consent/TTL-purge/pause-on-voice-mute
  are real (`aipc_rag/screen_audio.py`); the actual OCR + transcribe calls
  are not, because Phase 3 (`voice-stt-paraformer`) doesn't exist yet and
  the OCR model/runtime choice hasn't been made.
- **Firstboot consent screens don't exist.** The config files
  (`browser-consent.yaml`, `screen-audio.yaml`) are ready to be written by
  a wizard screen, but Phase 7's `ops-firstboot` wizard runner is itself
  only scaffolded — nothing to hand these screens off to yet.
- **All 5 modules stay `.disabled`** pending hardware verification on the
  actual Strix Halo AI PC (CLAUDE.md §9) — nothing here has been proven
  to actually run, only to render and import cleanly.
