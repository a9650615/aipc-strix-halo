## 1. Module Scaffolding (5 modules)

- [x] 1.1 `db-postgres`: scaffolded 2026-06-30, build-time fixed
  2026-07-01. README, files/, init SQL (`CREATE EXTENSION
  IF NOT EXISTS vector`), post-install.sh (idempotent, enable-only),
  verify.sh (port 5432 + extension check). `.disabled` stays pending
  hardware verify.
- [x] 1.2 `db-qdrant`: scaffolded 2026-06-30. README, quadlet,
  `.disabled`, verify.sh skip-when-disabled (`exit 2`).
- [x] 1.3 `rag-embedder`: scaffolded 2026-06-30, build-time fixed
  2026-07-01. README, quadlet (port 8201, iGPU devices), verify.sh
  (`/healthz` + service-active). **Descoped**: "post-install.sh cache
  warmup" — can't run at build time (no init, nothing to warm), same
  build/runtime lesson as the other 4 modules; correctly left
  enable-only. `embed-bge` alias now wired (2026-07-06, this pass) but
  unverified — the backing image (`docker.io/aipc/rag-embedder:latest`)
  has no source in this repo yet (see README).
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

- [x] 6.1 Quadlet on port 7000, `DATABASE_URL` points at the
  Postgres backend.
- [x] 6.2 `LITELLM_BASE_URL=http://127.0.0.1:4000` set in the
  quadlet env.
- [x] 6.3 Client config example (`memory.endpoint` +
  `AIPC_PRIMARY_USER`) in README.

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
- [ ] 12.2 Confirm Postgres + pgvector up, embedder /healthz 200,
  mem0 /healthz 200.
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
