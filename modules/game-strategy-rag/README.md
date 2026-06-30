# game-strategy-rag

Per-game strategy RAG framework. Ships an empty source registry — users add
per-game strategy sources at runtime.

## What it does

- Ships an empty source registry at `/etc/aipc/game-strategy/sources.yaml`.
- Creates `/var/lib/aipc/game-strategy/` at build time for runtime ingest cache.
- No host packages — strategy ingest runs via the LiteLLM gateway and Qdrant.

## Design decisions

- **D4**: Strategy-RAG framework with an empty source registry. Users populate sources per-game; the framework provides ingest, embedding, and retrieval against Qdrant.

## Notes

- The shipped `sources.yaml` is intentionally empty. Users add game-specific URLs/files.
- Ingest cache lives in `/var/lib/aipc/game-strategy/` (persistent across image rebuilds via /var).

## Dependencies

- `llm-litellm` (embedding and retrieval via LiteLLM gateway)
- `data-qdrant` (vector storage)

## Spec cross-ref

- `openspec/changes/phase-5-gaming/design.md` §D4
