## Why

Phase 1 stood up the LLM gateway; Phases 3–6 give the AI PC voice,
agents, gaming, and dev tools. Phase 2 is the layer that makes the
assistant *remember*: a vector store, an embedder + reranker, an
across-session memory framework (mem0), and four RAG ingest watchers
that index the user's actual desktop life (documents, code, browser
history, optionally screen + audio).

The architecture decision is that vectors live in **pgvector inside
Postgres by default**, with Qdrant available but `.disabled` until the
corpus warrants it (>1M vectors). One backend keeps backups, snapshots,
and access control simple; the upgrade path to Qdrant is a documented
migration command, not a fork in the design.

## What Changes

- **New capability `memory-rag`** covering the 5 Phase 2 modules as
  one coherent memory + RAG surface.
- **Postgres + pgvector as the primary vector store**: a single
  `db-postgres` quadlet hosting both relational mem0 metadata and the
  vector index. `db-qdrant` ships disabled.
- **mem0 as the memory framework** for across-session recall, wired
  to the local Postgres backend.
- **Embedder + reranker**: `bge-m3` for multilingual dense+sparse
  embeddings, `bge-reranker-v2-m3` for second-stage reranking. Both
  served as a single HTTP service exposed through the LiteLLM
  `embed-bge` alias (already declared in Phase 1).
- **Four RAG ingest watchers** under `rag-ingest`: Desktop documents,
  local code repos, browser history + bookmarks, and optional screen
  OCR + audio transcript. All default-on except where consent gates
  apply.
- **Browser capture is per-browser opt-in** at firstboot (Firefox
  places.sqlite, Chrome History db).
- **Screen OCR + audio transcript is strict opt-in** with a region
  selector and a default 7-day TTL.
- **All RAG data plane is local-only**: embedder, vectors, mem0
  storage. No source data leaves the machine; SearXNG (Phase 4) stays
  the sole network-egress component.
- **`aipc rag` CLI** for listing sources, status, reindex, and purge.

## Capabilities

### New Capabilities

- `memory-rag`: Host-side memory + RAG surface — pgvector primary
  store (Qdrant opt-in), mem0 framework, bge-m3 + reranker service,
  four ingest watchers with per-source consent rules, local-only data
  plane, and the `aipc rag` CLI. All LLM calls route through Phase 1
  LiteLLM (`embed-bge` alias plus any future reranker alias).

### Modified Capabilities

- `ai-runtime` (Phase 1): No requirement changes. The `embed-bge`
  alias already exists in Phase 1's LiteLLM config; Phase 2 supplies
  the backing service.

## Impact

- **`modules/`**: 5 new modules added (see tasks group 1). No
  existing module is touched.
- **`tools/aipc doctor`**: Gains a `memory-rag` section asserting
  Postgres + pgvector reachable, embedder `/healthz` ok, each
  enabled ingest service active, and mem0 server reachable.
- **`tools/aipc rag`**: New top-level subcommand (`list-sources`,
  `status`, `reindex <source>`, `purge <source>`).
- **`targets/bootc/Containerfile` + `targets/ansible/site.yml`**:
  Rendered outputs grow by 5 modules; both targets must reach the
  same end state. `db-qdrant` ships `.disabled` (renderer no-ops).
- **Firstboot wizard**: Gains consent prompts for browser-history
  capture (per browser) and screen+audio capture (with region
  selector). Owned by Phase 2 (the prompts), rendered by the Phase 7
  wizard runner.
- **Phase 3 dependency (soft)**: audio-transcript ingest reuses
  Phase 3's `voice-stt-paraformer` streaming service; if Phase 3 is
  not yet deployed, audio transcript stays disabled.
- **Phase 4 dependency**: agents will consume `memory-rag` via
  retrieval tools; no spec coupling in this change.
