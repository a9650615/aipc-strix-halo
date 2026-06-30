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
- Loads the `pgvector` extension on first boot via a runtime oneshot
  (`aipc-pg-init.service`) that applies `/usr/lib/aipc/init-pgvector.sql`.
- Publishes the connection URL at `env/endpoint` for downstream modules.
- Writes the default backend selector at `/etc/aipc/memory/backend`
  (`pgvector`).

## Build-time vs runtime split

`post-install.sh` is **build-time only**: it creates the sentinel
directory `/var/lib/aipc-pg` and `systemctl enable`s the two units
(`postgres.service`, `aipc-pg-init.service`). It does NOT start them
(no `--now`), does NOT probe the port, does NOT call `psql` — none of
those work at image-build time.

All runtime concerns live in systemd units:

- `quadlet/postgres.service` — the postgres container, started by the
  init system at boot.
- `files/etc/systemd/system/aipc-pg-init.service` — a `Type=oneshot`
  runtime unit that waits for postgres readiness, creates the `aipc`
  database if missing, applies the pgvector SQL, then touches
  `/var/lib/aipc-pg/.initialized`. `ConditionPathExists=!…/.initialized`
  guarantees it runs once. `Requires=postgres.service` / `After=…`
  order it after the quadlet. This mirrors the
  `aipc-decrypt-cloud-keys.service` oneshot pattern from `secrets-sops`.

## Files inventory

| Source (in module) | Target path on image | Purpose |
|---|---|---|
| `quadlet/postgres.service` | `/etc/containers/systemd/postgres.service` | Postgres 16 container quadlet |
| `files/etc/systemd/system/aipc-pg-init.service` | `/etc/systemd/system/aipc-pg-init.service` | Runtime schema-init oneshot |
| `files/usr/lib/aipc/pg-init.sh` | `/usr/lib/aipc/pg-init.sh` (0755) | Readiness wait + idempotent schema bootstrap |
| `files/usr/lib/aipc/init-pgvector.sql` | `/usr/lib/aipc/init-pgvector.sql` | `CREATE EXTENSION IF NOT EXISTS vector` |
| `files/etc/aipc/memory/backend` | `/etc/aipc/memory/backend` | Default vector backend selector (`pgvector`) |
| `env/endpoint` | (consumed by renderer) | Connection URL for downstream modules |

> The SQL init file lives under `/usr/lib/aipc/`, not `/usr/local/lib/`:
> on bootc `/usr/local` is a symlink to `/var/usrlocal` and is not
> writable at build time. This is the same trap that hit `secrets-sops`
> (503c175) and the original `db-postgres` scaffold (cf886a1).

## Endpoint

`postgresql://127.0.0.1:5432/aipc`

## Dependencies

- `system-base`.

## Status

`.disabled` is present and stays present. The refactor is structural —
the module builds cleanly and the runtime init path is correct — but
enablement requires hardware verification on the AI PC (Strix Halo):
postgres must actually start, accept the `aipc` DB, and load pgvector
before this module is flipped on.
