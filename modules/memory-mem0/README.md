# memory-mem0

mem0 memory framework server. Stores across-session user facts
(preferences, ongoing projects, people, recurring intents) in Postgres
and exposes them over HTTP for the Phase 4 agents and CLI.

## Design decisions

- **D2** — mem0 chosen over Letta / Cognee / hand-rolled for v1.
  Lightest operational footprint and integrates with LiteLLM out of the
  box.
- **D5** — every LLM call mem0 makes (summarisation, fact extraction)
  routes through the LiteLLM gateway at `http://127.0.0.1:4000`; the
  model namespace (`router-1b`, `main-70b`, …) is the public surface.

## What it does

- Runs the mem0 server as a podman quadlet bound to `127.0.0.1:7000`.
- Persists memory to the Postgres database provided by `db-postgres`.
- Talks to LiteLLM for its internal LLM calls.

## Build-time vs runtime split

`post-install.sh` is **build-time only**: it runs `systemctl enable
mem0.service` (no `--now`). It does NOT start the service, probe
`/healthz`, or call any client — none of those work at image-build time
(no init, nothing listening on 7000). The original scaffold did all
three and would hang/fail on every rebuild.

mem0 needs no host-side runtime init: the container self-manages its
schema via `DATABASE_URL`, and the quadlet already orders it
`After=postgres.service llm-litellm.service` / `Requires=postgres.service`.
Runtime health is asserted by `verify.sh` (`systemctl is-active` +
`curl /healthz`), which is the correct place for it.

> **Quadlet deployment gap (pre-existing, blocks enablement).** The
> bootc renderer COPYs `files/`, `modprobe.d/`, `env/` but does NOT
> install `quadlet/`. This module's `post-install.sh` enables
> `mem0.service` without installing the quadlet file, so the unit is
> absent at build — `systemctl enable` would fail if `.disabled` were
> removed today. Same gap affects `db-postgres`, `llm-ollama`,
> `rag-embedder`, `rag-ingest`. Resolving it (install target +
> `.service`-vs-`.container` naming) is a cross-cutting decision that
> needs an OpenSpec change, not a per-module patch.

## Endpoint

`http://127.0.0.1:7000`

## Client config example (Phase 4 agents)

```yaml
memory:
  endpoint: http://127.0.0.1:7000
  user_id: ${AIPC_PRIMARY_USER}
```

## Dependencies

- `db-postgres`.
- `llm-litellm`.
