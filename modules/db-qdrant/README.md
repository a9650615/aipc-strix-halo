# db-qdrant

Qdrant vector store — opt-in upgrade path from pgvector for deployments
where the RAG corpus crosses ~1M vectors or where filtered ANN queries
start to slow.

## Design decisions

- **D1** — pgvector is the default backend; this module ships `.disabled`
  and is enabled via the documented `aipc db migrate qdrant` path.
  Coexists with `db-postgres` during migration (mem0 metadata stays in
  Postgres).

## What it does

- Runs Qdrant as a podman quadlet bound to `127.0.0.1:6333`.
- Stores vectors at `/qdrant/storage` on the `aipc-qdrant-data` volume.

## Endpoint

`http://127.0.0.1:6333`

## Migration

```
aipc db migrate qdrant
```

Re-indexes existing RAG content from pgvector into Qdrant, then flips
`/etc/aipc/memory/backend` from `pgvector` to `qdrant`. `db-postgres`
stays running (mem0 metadata).

## Dependencies

- `db-postgres` (coexists during migration).
