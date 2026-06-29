# db-postgres

Postgres 16 with the `pgvector` extension. Primary vector store for RAG
and relational metadata store for mem0.

## Design decisions

- **D1** — pgvector is the default vector backend. `db-qdrant` is the
  documented opt-in upgrade path when corpus size crosses ~1M vectors.
- **D2** — mem0 stores its metadata in this same database
  (`memory-mem0` depends on `db-postgres`).

## What it does

- Runs Postgres 16 as a podman quadlet, bound to `127.0.0.1:5432` only
  (local-only trust auth; no network exposure).
- Loads the `pgvector` extension on first boot via
  `/usr/local/lib/aipc/init-pgvector.sql`.
- Publishes the connection URL at `env/endpoint` for downstream modules.
- Writes the default backend selector at `/etc/aipc/memory/backend`
  (`pgvector`).

## Endpoint

`postgresql://127.0.0.1:5432/aipc`

## Dependencies

- `system-base`.
