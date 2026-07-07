## 1. Module Scaffolding (5 modules)

- [x] 1.1 `db-postgres`: scaffolded 2026-06-30, build-time fixed
  2026-07-01. README, files/, init SQL (`CREATE EXTENSION
  IF NOT EXISTS vector`), post-install.sh (idempotent, enable-only),
  verify.sh (port 5432 + extension check). `.disabled` stays pending
  hardware verify.
- [x] 1.2 `db-qdrant`: scaffolded 2026-06-30. README, quadlet,
  `.disabled`, verify.sh skip-when-disabled (`exit 2`).
- [x] 1.3 `rag-embedder`: scaffolded 2026-06-30, build-time fixed
  2026-07-01. **Superseded 2026-07-07**: the quadlet's
  `docker.io/aipc/rag-embedder:latest` never had a real source anywhere
  (same root-cause class as memory-mem0) — replaced with a native
  `aipc-rag-embedder.service` (systemd + venv) running a small FastAPI
  wrapper around `sentence-transformers`' `BAAI/bge-m3`, CPU-only for
  now (`ponytail:` — swap for Lemonade/iGPU once that runtime exposes an
  embeddings API). Real functional round trip on this dev host: real
  venv built, real weights downloaded, `GET /healthz` → 200, `POST
  /v1/embeddings` → real 1024-dim vector, and confirmed LiteLLM's
  `embed-bge` alias resolves through it end-to-end
  (`http://127.0.0.1:4000/v1/embeddings` → 200). Found and fixed a real
  bug along the way: `sentence-transformers.encode()` returns
  `numpy.float32`, which FastAPI/pydantic can't JSON-serialize — cast to
  native `float`. **Updated 2026-07-08**: hardware-verified on the physical
  AI PC; bge-m3 is pre-staged under `HF_HOME`, the unit runs offline, and
  the venv entrypoints are relabeled `bin_t` so systemd does not leave the
  service in `init_t`. `bge-reranker-v2-m3`/`/rerank` **not implemented**
  (nothing in the current write path calls it; separate follow-up). See
  `modules/rag-embedder/README.md`.
- [~] 1.4 `rag-ingest`: scaffolded 2026-06-30 (README, 5 systemd
  units, consent config skeletons), build-time bug fixed 2026-07-06
  (`--now` removed, fake `pip install aipc-rag-ingest` dropped — see
  post-install.sh ponytail note). **Not implemented**: the four
  watcher binaries the units `ExecStart=` (`aipc-rag-desktop`,
  `aipc-rag-code`, `aipc-rag-browser`, `aipc-rag-screen-audio`) don't
  exist anywhere in the repo — see group 5.
- [x] 1.5 `memory-mem0`: scaffolded 2026-06-30, build-time fixed
  2026-07-01. README, quadlet (port 7000), verify.sh (`/healthz` +
  service-active). **Partial**: verify.sh only checks `/healthz`, not
  "sample write+read round-trip" as originally scoped — round-trip
  needs a live gateway + running mem0, i.e. hardware-verified only.

## 2. Postgres + pgvector

- [x] 2.1 Quadlet runs Postgres 16, binds `127.0.0.1:5432`,
  persistent volume `aipc-postgres-data` on `/var/lib/postgresql/data`.
- [x] 2.2 Init SQL loads `pgvector`; `aipc-pg-init.service` runtime
  oneshot creates the `aipc` database (role: trust-auth `postgres`,
  no separate app role — simpler than spec'd "database + role", flagged
  not re-litigated here).
- [x] 2.3 `/etc/aipc/memory/backend` defaults to `pgvector`.

## 3. Qdrant (Disabled By Default)

- [x] 3.1 Quadlet declared but `.disabled`; both renderers'
  `discover()` skip it centrally (`quadlet-render-support`, 2026-07-01).
- [x] 3.2 `db-qdrant/README.md` documents the `aipc db migrate
  qdrant` path. Note: the CLI command itself (`aipc db migrate
  qdrant`) is not implemented — this task only required documenting
  the path, not building it; tracked as a real future gap, not part
  of this task's literal scope.

## 4. bge-m3 + Reranker Service

- [x] 4.1 Quadlet runs a single HTTP service hosting both models
  (scaffold; real backing image not built yet, see 1.3).
- [x] 4.2 `embed-bge` alias added to both `models.yaml` and
  `llm-litellm`'s `config.yaml` (2026-07-06, this pass) — it had
  actually been *cut* 2026-07-04 as an "unused extra" before
  rag-embedder needed it; re-added pointing at
  `http://127.0.0.1:8201/v1`. Unverified (no backing image, no
  hardware).
- [x] 4.3 `/rerank` documented in README, alongside the new
  `/v1/embeddings` OpenAI-compat contract needed for the LiteLLM
  alias to actually reach `/embed` (2026-07-06 addition — LiteLLM's
  `openai/` provider always calls `{api_base}/embeddings`).

## 5. RAG Ingest Watchers

- [ ] 5.1-5.4 **Not implemented.** Desktop/code/browser/screen-audio
  watcher logic (poll, diff-index, chunk, embed, write to pgvector)
  doesn't exist — only systemd unit skeletons pointing at binaries
  that were never written (see 1.4). Deferred 2026-07-06: browser
  history parsing, code chunking, and OCR/audio-transcript are each
  a "pick a mature library, don't hand-roll" decision — bringing
  options back as a proposal before implementing, per user direction,
  rather than improvising in this pass. Screen+audio (5.4) is further
  blocked on Phase 3 (`voice-stt-paraformer`) not existing yet
  (proposal's own Q2, still open).

## 6. mem0 Server + Wiring

- [x] 6.1 ~~Quadlet on port 7000~~ **superseded 2026-07-06**: the
  quadlet's `docker.io/mem0/mem0:latest` image doesn't exist and the
  real published image (`mem0/mem0-api-server`) has no amd64 variant —
  replaced with a native `aipc-mem0.service` (systemd + venv) wrapping the
  real `mem0ai` PyPI package, same port 7000, real pgvector connection
  functionally verified against a live `db-postgres` container on this
  dev host (not the physical AI PC). See `modules/memory-mem0/README.md`.
- [x] 6.2 LiteLLM gateway wiring: `openai_base_url=http://127.0.0.1:4000`
  set for both the `llm` (ornith-35b) and `embedder` (embed-bge)
  configs — verified for real. **2026-07-07**: the `embed-bge` gap is
  now closed (see 1.3, `rag-embedder`); a full real add→embed→pgvector
  round trip passes end-to-end. Found and fixed two real bugs in the
  process — `Memory.add()` has no `app_id` kwarg (mem0ai==2.0.11),
  and `Memory.search()` needs a flat `filters` dict, not the nested
  `{"OR": [...]}` scheme the Platform API's docs describe — see
  `modules/memory-mem0/README.md`'s Verification section for the full
  trace.
- [x] 6.3 Client config example (`memory.endpoint` +
  `AIPC_PRIMARY_USER`) in README.
- [x] 6.4 **New, 2026-07-07**: `aipc mem0 migrate-from-saas` CLI
  (`tools/aipc_lib/mem0_migrate.py` + `cli.py`) pulls all Mem0 SaaS
  memories (every user/agent/app/run scope, via a real `filters` OR
  block against `/v3/memories/`) and imports them into the local
  `aipc-mem0.service`, preserving every scope field. Dry-run by default;
  `--apply` writes for real. API key read from `--key-file` or
  `$MEM0_API_KEY`, never logged or written to any repo file. **Found and
  fixed a real bug**: the SaaS API rejects `Authorization: Bearer <key>`
  (401 `token_not_valid`) — it requires `Authorization: Token <key>`,
  confirmed via a live probe against the real API. **Migration itself
  is blocked today**: this account's SaaS usage quota is exhausted
  (1000/1000 this billing period, resets 2026-08-01) — confirmed via a
  real `429` response, same quota this session's own `mem0` MCP tool
  calls were hitting. Not a code issue; re-run `aipc mem0
  migrate-from-saas --apply --key-file <path>` after the reset (or on a
  higher-tier plan) to actually pull the data over.
- [x] 6.5 **New, 2026-07-08**: local stdio MCP server added for the
  self-hosted stack (`aipc_mem0.mcp_server`) because the official Mem0 MCP is
  SaaS-only. The service is the primary unit; Claude Code plugin-cache
  repointing is exposed as the `mem0 local service` row in `aipc config tools`
  (`Configure Claude` / `Re-apply Claude`), with `aipc config tools --mem0-local`
  for headless use and `tools/aipc_mem0_point_mcp_local.sh` as the fallback.
  opencode and hermes were configured to the same local MCP on the live machine.
  Hardware-verified with real add/search calls through local bge-m3 + pgvector.
  Found and fixed the `history.db` ownership bug with
  `aipc-mem0-state-dir.service`, resolving the primary user dynamically instead
  of hardcoding a username.

## 7. `aipc rag` CLI

- [ ] 7.1-7.5 **Not implemented.** `reindex`/`purge`/`status`
  semantics depend on the group-5 schema decision (deferred above) —
  building the CLI ahead of that would lock in a shape before the
  storage design is settled.

## 8. Firstboot Consent Prompts (joint with Phase 7)

- [ ] 8.1-8.3 **Blocked on Phase 7.** `ops-firstboot` (Phase 7) is
  itself only `.disabled`-scaffolded, no wizard runner exists to
  contribute a screen to. Consent config *files*
  (`browser-consent.yaml`, `screen-audio.yaml`) already exist with
  safe defaults (`consent: false`, `enabled: false`) — only the
  interactive wizard screens are missing.

## 9. Doctor Checks

- [~] 9.1 Partially covered — each module's `verify.sh` already
  gives `aipc doctor` (which just maps `verify.sh` exit codes, see
  `tools/aipc_lib/doctor.py::run_all`) most of this for free:
  Postgres+pgvector ✓, rag-embedder `/healthz` ✓, mem0 `/healthz` ✓.
  Desktop+code watcher checks exist in rag-ingest's verify.sh but
  will always FAIL until group 5 ships. **Missing**: an explicit
  "active backend matches `/etc/aipc/memory/backend`" assertion —
  deferred alongside group 5/8 (needs the schema decision first).
- [ ] 9.2 Browser/screen-audio INFO-not-FAIL status: done (rag-ingest
  verify.sh already treats these as informational). Vector-count
  threshold warning: **not implemented** — needs the group-5 schema
  (table name) decided first; deferred.

## 10. Documentation

- [x] 10.1 Per-module README exists for all 5 modules (each documents
  its own known gaps inline rather than pretending to be finished).
- [ ] 10.2 `docs/memory-rag.md` — **not written**. Deferred until the
  group-5 design proposal is settled, so the end-to-end diagram
  describes what's actually built rather than the aspirational
  original design.
- [x] 10.3 Confirmed 2026-07-06: `docs/architecture.md §7` Phase 2
  row lists the same 5 modules, no count change needed. (Unrelated
  pre-existing wording nit: the `rag-ingest` row's purpose text
  mentions "email+calendar," which isn't one of this proposal's four
  sources — not touched, out of scope for this pass.)

## 11. Local Build Verification

- [x] 11.1 `render bootc` runs clean (2026-07-06). All 5 modules are
  currently `.disabled`, so `discover()` correctly excludes all of
  them from output — nothing to include yet, not a failure.
- [x] 11.2 `render ansible` runs clean, output parses as valid YAML
  (2026-07-06). No `--check` flag exists on this CLI; ran the plain
  render instead.
- [ ] 11.3 **Not run.** Needs a privileged container (systemd +
  postgres actually running) to execute `verify.sh` meaningfully —
  out of reach without hardware/a real container runtime in this
  session. `sh -n` syntax-checked and `python3 -m py_compile`'d
  every touched script instead (static, not the same as this task).

## 12. AI PC Hardware Verification

- [ ] 12.1 Deploy `:rolling` tag to the AI PC via `bootc switch`.
- [x] 12.2 **Hardware-verified 2026-07-08 on the live AI PC**: Postgres +
  pgvector up, `aipc-rag-embedder` `/healthz` 200, `aipc-mem0` `/healthz`
  200, `embed-bge` via LiteLLM returns real bge-m3 embeddings, and mem0
  add/search round-trips through pgvector.
- [ ] 12.3 Drop a file into `~/Desktop`; confirm a vector appears
  within one watcher cycle.
- [ ] 12.4 Opt in to Firefox capture via the wizard; confirm
  history vectors populate.
- [ ] 12.5 Opt in to screen+audio capture; choose a region + TTL;
  confirm vectors populate and TTL applies.
- [ ] 12.6 Smoke-test `aipc rag purge screen-audio --confirm`;
  confirm all sourced vectors gone.

## 13. Archive Change

- [ ] 13.1 Run `npx -y @fission-ai/openspec validate phase-2-memory
  --strict` — must print `Change 'phase-2-memory' is valid`.
- [ ] 13.2 Run `npx -y @fission-ai/openspec archive phase-2-memory`
  to merge the spec into `openspec/specs/memory-rag/spec.md` and
  close the change.
