# agent-tools-search

Search backend: SearXNG (default, local container) + Tavily (opt-in, API key).

SearXNG runs as a quadlet container bound to loopback.
Tavily is only advertised when `TAVILY_API_KEY` is set in the
SOPS-encrypted secrets.

## Current status: quadlet + tool wrapper implemented, still `.disabled`

The quadlet + `settings.yml` (JSON format enabled) were already correct
before this pass. Implemented now (tasks 4.5, 4.6):

- `files/usr/lib/aipc-agent/aipc_agent_tools_search/search.py` — stdlib
  (`urllib.request`) client, no new HTTP dependency, same fail-soft
  pattern as `agent-orchestrator/aipc_agent/memory.py`:
  - `search_searxng(query, limit=5)` — GETs `env/endpoint`
    (`http://127.0.0.1:8888`, override via `AIPC_SEARXNG_ENDPOINT`)
    `/search?q=...&format=json`, normalizes to
    `{"status": "ok"/"error", "results": [{"title","url","content"}]}`.
    Never raises — an unreachable/malformed response returns
    `status: "error"`.
  - `search_tavily(query, limit=5)` — only calls out when
    `TAVILY_API_KEY` is configured; returns
    `{"status": "not_configured", "results": []}` (not an error) when
    absent. Never bakes a key (CLAUDE.md §5).
  - `available_tools()` — `["search.searxng"]`, plus `"search.tavily"`
    only when a key is actually present. This is what `verify.sh` and
    (eventually) `supervisor.yaml`'s tool advertisement should call.
- `verify.sh`: static syntax check + `self_test()` (JSON normalization,
  fail-soft against a closed port, `not_configured`-without-key path) +
  the `available_tools()` opt-in check, all render-verified. The SearXNG
  quadlet liveness check (`aipc-searxng.service` active + port 8888
  reachable) only runs, and only needs to pass, on real hardware with a
  container runtime — this environment has neither, so that branch
  reports render-verified and does not claim more.

## Known gap: Tavily key doesn't reach this module yet

`TAVILY_API_KEY` lookup order is `os.environ["TAVILY_API_KEY"]`, then
`/etc/aipc/env.d/llm-litellm/cloud-keys.env` (override via
`AIPC_TAVILY_ENV_FILE`) — the file `modules/secrets-sops`'s
`aipc-decrypt-cloud-keys.service` / `decrypt-cloud-keys.sh` actually
writes today. That script's `awk` filter only extracts
`anthropic_api_key` / `openai_api_key` / `gemini_api_key` from
`secrets/cloud-llm.yaml` — it does **not** extract `tavily_api_key` yet,
even though `secrets/cloud-llm.yaml.example` now documents the field
(added in this pass, task 4.6's "appends the key to the schema"). Until
`modules/secrets-sops/files/usr/lib/aipc/decrypt-cloud-keys.sh` gains a
`tavily_api_key -> TAVILY_API_KEY=` line, `search_tavily()` will always
return `not_configured` at runtime even with a key set in the secret —
this is a real spec gap, not a bug in this module; `modules/secrets-sops`
is outside this task's reserved file list and needs its own follow-up.

## Dependencies
- secrets-sops (Tavily API key decryption)
- llm-litellm

## Spec
openspec/changes/phase-4-agent — tasks 1.7, 4.5, 4.6
