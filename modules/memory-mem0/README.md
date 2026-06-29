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
