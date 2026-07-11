# memory-mem0

mem0 memory framework server. Stores across-session user facts
(preferences, ongoing projects, people, recurring intents) in Postgres
(pgvector) and exposes them over HTTP for the Phase 4 agents and CLI.

## Design decisions

- **D2** — mem0 chosen over Letta / Cognee / hand-rolled for v1.
  Lightest operational footprint and integrates with LiteLLM out of the
  box.
- **D5** — every LLM/embedding call mem0 makes routes through the LiteLLM
  gateway at `http://127.0.0.1:4000` (CLAUDE.md §7); the model namespace
  (`ornith-35b` for fact extraction, `embed-bge` for embeddings) is the
  public surface. mem0's own bundled `litellm` provider is a different
  thing (the in-process litellm SDK making its own direct calls to real
  backends) — the `openai` provider with `openai_base_url` pointed at the
  gateway is used instead, matching `agent-orchestrator`'s
  `custom_llm_provider="openai"` pattern.

## What it does — native systemd + venv, not a container

**Root-cause finding, 2026-07-06**: the original quadlet's
`docker.io/mem0/mem0:latest` does not exist (`skopeo inspect` returns
"requested access to the resource is denied"). The real published image is
`mem0/mem0-api-server`, but Docker Hub only lists `arm64`/`unknown`
architecture variants for it — no `amd64` — so it cannot run on this
hardware either way. Same root-cause class this repo has hit repeatedly
(voice-stt-sensevoice, dev-ai-mcp-dev-servers, agent-browser): a fictitious
or wrong-architecture prebuilt image. Fixed the same way those were fixed:
replaced the container with a native systemd service (`aipc-mem0.service`)
running a small FastAPI wrapper (`aipc_mem0/server.py`) around the real
`mem0ai` PyPI package (2.0.11) in a venv at `/usr/lib/aipc-mem0/venv`.

- `vector_store`: `pgvector`, pointed at `db-postgres`'s `aipc` database
  (`mem0_memories` collection, 1024 dims — bge-m3 dense output, matching
  `rag_chunks`'s own dimension).
- `llm`: `openai` provider, `model=ornith-35b`, `openai_base_url` at the
  LiteLLM gateway.
- `embedder`: `openai` provider, `model=embed-bge`, same gateway.
- `MEM0_TELEMETRY=False` in the unit — mem0 defaults to phoning home to
  PostHog (`us.i.posthog.com`) on every call; disabled to match CLAUDE.md
  §6's offline requirement, not something to silently leave on.

## Build-time vs runtime split

`post-install.sh` is **build-time only**: builds the venv, installs
pinned requirements, creates `/var/lib/aipc-mem0` (mem0's own SQLite
history store lives there — separate from the Postgres vector store), relabels
the venv entrypoints for the systemd SELinux transition, and enables
`aipc-mem0-state-dir.service` + `aipc-mem0.service` (no `--now`). Nothing is
probed or started at image-build time.

## Verification (2026-07-06, updated 2026-07-07)

Real functional testing on this dev host via podman (not the physical AI
PC — not a CLAUDE.md §9 hardware-verified claim):

- Started the real `pgvector/pgvector:pg16` image (the one `db-postgres`
  actually uses) via podman, applied the real `init-pgvector.sql` —
  confirmed the `:ro,Z` SELinux relabel flag `db-postgres`'s quadlet
  already carries is in fact required (a bare `:ro` mount 403s on this
  SELinux host); the module's own quadlet config was already correct.
- `Memory.from_config(CONFIG)` against that real Postgres: **succeeds**
  — real pgvector connection, real collection creation. Found and fixed a
  real dependency gap along the way: mem0's pgvector backend imports
  `psycopg_pool`, so plain `psycopg[binary]` isn't enough —
  `requirements.txt` now pins `psycopg[binary,pool]`.
- Ran the real FastAPI app over real HTTP: `GET /healthz` → `200
  {"status":"ok"}`.
- **2026-07-07 — `rag-embedder` stood up for real** (see its own README),
  clearing the `embed-bge` gap this doc previously documented as the
  "one remaining real blocker". With a real embedder answering
  `http://127.0.0.1:4000/v1/embeddings`, a full real
  add → embed → pgvector-write → search → pgvector-read round trip was
  run against real services (no mocks): `POST /memories` and
  `POST /search` both `200`, row confirmed in `mem0_memories` via
  `psql`.
- **Two real bugs found and fixed by that round trip** (found first with
  `agent_id`/`app_id`/`run_id` all populated — exactly the shape this
  README's own client example uses):
  1. `Memory.add()` in the real `mem0ai==2.0.11` package (confirmed via
     `inspect.signature`) only accepts `user_id`/`agent_id`/`run_id` — no
     `app_id` kwarg. `add_memory()` previously passed `app_id` straight
     through and crashed with `TypeError` on every call that set it.
     Fixed: `app_id` is now folded into `metadata["app_id"]` instead of
     passed as a kwarg — still fully preserved, and still filterable
     (see below).
  2. `Memory.search()` requires `filters` as a **flat** dict containing
     at least one of `user_id`/`agent_id`/`run_id` at the top level —
     not the Platform API's nested `{"OR": [...]}` scheme. The previous
     `_scope_filter()` wrapped multiple scopes in `"OR"` and crashed with
     `ValueError: filters must contain at least one of: user_id,
     agent_id, run_id` on any search using 2+ scope keys. Fixed:
     `_scope_filter()` now returns a flat dict; multiple keys AND
     together for real (verified), and `app_id` rides along as a plain
     metadata-equality key in the same flat dict (also verified for
     real: a non-matching `app_id` correctly returns `[]`, a matching
     one correctly returns the memory).
- Confirmed both fixes against a second, independent real Postgres +
  real embedder + real mem0ai round trip (not just the unit tests):
  `POST /memories` with all four scope fields set → `200`; `POST
  /search` with `user_id`+`agent_id`+`app_id`+`run_id` all set → `200`
  with the memory returned; the same search with a wrong `app_id` →
  `200` with `"results": []`.

**Net verification tier**: **hardware-verified 2026-07-08** on the physical
Strix Halo AI PC (see the next section). Previously functional/render-verified
in podman on the dev host.

## Hardware-verified + local MCP for Claude/opencode/hermes (2026-07-08)

Stood the whole stack up on the real machine (not podman): built
`/usr/lib/aipc-mem0/venv` (mem0ai 2.0.11), started `aipc-rag-embedder` +
`aipc-mem0`, and ran a real `add → embed(bge-m3) → pgvector → search` round
trip — both with `infer=false` (embed+store only) and `infer=true` (the local
`ornith-35b` extracts structured facts via the LiteLLM gateway, ~90 s on the
35B). `mem0_memories` table auto-created in the `aipc` db; rows confirmed via
`podman exec aipc-postgres psql`. **Module is now enabled** (`.disabled`
removed); the live machine also `systemctl enable`s both services.

Three real root-cause bugs were found and fixed on the way (all the
"renders clean, lint green, only fails on hardware" class from §9):

1. **SELinux `init_t` confinement.** The venv's `python3`/`uvicorn` shipped
   labeled `etc_t` (live hotfix under `/etc/aipc/...`) / `lib_t` (baked
   `/usr/lib/aipc-...`). Neither triggers `init_t`'s service-domain
   transition, so the process stays in `init_t` — which this image's policy
   (the custom `aipc_agent_network` module) denies both **outbound network**
   (EACCES connecting to huggingface.co) and **oneDNN JIT mmap-exec**
   (`RuntimeError: could not create a primitive` in the GELU activation).
   A `systemd-run` transient service (which execs a `bin_t` binary and lands
   in `unconfined_service_t`) works; the unit didn't. **Fix**: relabel
   `…/venv/bin` to `bin_t` (`semanage fcontext` + `restorecon` in
   `post-install.sh`, persistent; `chcon` as a build-env fallback) so the
   normal `init_t → unconfined_service_t` transition fires. (Forcing
   `SELinuxContext=unconfined_service_t` directly failed with `203/EXEC` —
   `etc_t` isn't a valid entrypoint for that domain; the label is what
   matters.)

2. **bge-m3 weights not staged + runtime HF fetch.** `rag-embedder` loads
   `BAAI/bge-m3` lazily via sentence-transformers, which tries HuggingFace at
   first request — but (a) the service's `init_t` context denies egress, and
   (b) §6 requires offline load once weights are present. The first embed
   hung ~3 min then 500'd. **Fix**: pre-stage the weights in the service's
   `HF_HOME` (`huggingface-cli download BAAI/bge-m3`) and set
   `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` in the unit. (Weight
   pre-staging is a runtime/firstboot concern — `post-install.sh` is
   build-time with no HF access per §8; tracked there as a NOTE.)

3. **`history.db` ownership.** mem0's SQLite history store
   (`/var/lib/aipc-mem0/history.db`) is written by both the root systemd
   service AND the per-agent MCP servers (launched by Claude/opencode/hermes
   as the primary user). A root-owned dir made agent `add_memory` fail with
   `attempt to write a readonly database`. **Fix**: `aipc-mem0-state-dir.service`
   runs at boot, resolves `AIPC_PRIMARY_USER` (or the first uid 1000-59999),
   and recursively chowns `/var/lib/aipc-mem0` without hardcoding a username. The live
   machine was hand-fixed first; the repo now carries the durable boot fix.

### Local MCP server (no SaaS)

The official mem0 Claude plugin ships **only** a remote HTTP MCP at
`https://mcp.mem0.ai/mcp/` (authenticated with `MEM0_API_KEY`) — it has no
local/self-hosted mode, and `mem0ai==2.0.11` ships no MCP entrypoint (no
`mcp` dep, no `mem0 mcp` CLI). `aipc_mem0/mcp_server.py` is the local
equivalent: a stdio MCP server wrapping `Memory.from_config(CONFIG)` (same
config as the REST server) with the same tool surface as the platform MCP
(`add_memory`, `search_memories`, `get_memories`, `get_memory`,
`delete_memory`, `delete_all_memories`). It sets `MEM0_TELEMETRY=False`
itself before importing mem0 (it's launched by agents, not systemd).
Verified end-to-end with a real `mcp` stdio client.

### Pointing agents at local mem0

All three coding agents now share one local `mem0_memories` pgvector store
instead of the SaaS quota:

- **Claude Code** — the local mem0 service is the source of truth;
  `aipc config tools` exposes a **mem0 local service** row whose
  `Configure Claude` / `Re-apply Claude` action rewrites the plugin's cached
  `.mcp.json` (`~/.claude/plugins/cache/mem0-plugins/mem0/<ver>/.mcp.json`)
  from the SaaS HTTP server to a stdio launch of `aipc_mem0.mcp_server`
  (keeps the plugin's skills/hooks + tool prefix; just retargets the
  transport). A plugin **update overwrites this** — re-apply from that TUI row,
  with `aipc config tools --mem0-local` for headless use or
  `tools/aipc_mem0_point_mcp_local.sh` as the idempotent fallback.
- **opencode** — `~/.config/opencode/config.json` `mcp.mem0` (local stdio).
  opencode was already on the local LiteLLM gateway (`baseURL
  http://127.0.0.1:4000/v1`); this adds memory. NB: works when opencode runs
  native; the hermes distrobox doesn't see the host `/etc/aipc/mem0` path.
- **hermes** — `~/.hermes/config.yaml` `mcp_servers.mem0` (stdio, 600 s
  timeout for the 35B fact-extraction). hermes was already fully local
  (`coder-agentic` + MoA `local-power-duo` = resident-small+ornith-35b, all
  API keys unset). (Deeper option, not taken: hermes's own mem0 plugin has
  an OSS/self-hosted mode via `hermes memory setup mem0` — MCP is uniform
  across the three agents instead.)

Other MCPs in the session were evaluated: `context-mode` is already local
(file KB); `ccs-websearch` / `web-reader` are inherently network tools;
`image-analysis` has no local VLM backend (vlm-qwen2vl was cut). Only mem0
had a ready local backend, so only it was repointed.

## Endpoint

`http://127.0.0.1:7000`

Routes: `GET /healthz`, `POST /memories`
(`{messages, user_id, agent_id, app_id, run_id, metadata, infer}` —
`app_id` is folded into `metadata["app_id"]` before calling `Memory.add()`,
since the underlying library has no native `app_id` parameter),
`POST /search` (`{query, user_id, agent_id, app_id, run_id, limit}` — all
scope keys present are ANDed together as a flat `filters` dict),
`GET /memories` (query params `user_id/agent_id/run_id/app_id/limit`, all
optional — no scope lists everything; backs the portal's Memory tab, so it
calls `Memory._get_all_from_vector_store()` directly because the public
`get_all()` in mem0ai==2.0.11 rejects unscoped filters),
`DELETE /memories/{id}`.

## Client config example (Phase 4 agents)

```yaml
memory:
  endpoint: http://127.0.0.1:7000
  user_id: ${AIPC_PRIMARY_USER}
```

`agent-orchestrator/aipc_agent/memory.py` already speaks this contract
(`recall`/`remember`, fails soft if unreachable or the route shape
differs).

## Dependencies

- `db-postgres` (must be enabled and reachable at `127.0.0.1:5432`
  first — `aipc-mem0.service`'s `Requires=postgres.service`).
- `llm-litellm`, with `embed-bge` actually loaded (see verification
  note above — this is the one remaining real blocker on this dev host).
