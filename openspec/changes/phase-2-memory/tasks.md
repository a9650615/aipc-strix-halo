## 1. Module Scaffolding (5 modules)

- [ ] 1.1 `db-postgres`: create `modules/db-postgres/` with README,
  files/ for the Postgres 16 quadlet (volume on `/var/lib/aipc-db`),
  init SQL that creates the `aipc` database and loads `pgvector`,
  post-install.sh (idempotent extension load), verify.sh (port 5432
  reachable, extension installed).
- [ ] 1.2 `db-qdrant`: create `modules/db-qdrant/` with README,
  files/ for the Qdrant quadlet (volume on `/var/lib/aipc-qdrant`),
  **named with `.disabled` suffix** so the renderer skips it,
  verify.sh (skip-when-disabled).
- [ ] 1.3 `rag-embedder`: create `modules/rag-embedder/` with
  README, files/ for the HTTP service quadlet hosting bge-m3 + bge
  reranker on port 8201, mounted on the iGPU via Lemonade,
  post-install.sh (cache warmup), verify.sh (`/healthz` returns
  200, `embed-bge` alias resolves through LiteLLM).
- [ ] 1.4 `rag-ingest`: create `modules/rag-ingest/` with README,
  files/ for the four watcher services (`aipc-rag-desktop.service`,
  `aipc-rag-code.service`,
  `aipc-rag-browser-{firefox,chrome}.service`,
  `aipc-rag-screen-audio.service`), enable Desktop + code by
  default, leave browser + screen+audio disabled, verify.sh
  (Desktop + code active, others disabled-by-default).
- [ ] 1.5 `memory-mem0`: create `modules/memory-mem0/` with README,
  files/ for the mem0 service on port 7000 pointing at the active
  vector backend declared in `/etc/aipc/memory/backend`, verify.sh
  (`/healthz` returns 200, sample write+read round-trips).

## 2. Postgres + pgvector

- [ ] 2.1 Quadlet runs Postgres 16 (Bazzite-compatible image),
  binds to `127.0.0.1:5432`, persistent volume on
  `/var/lib/aipc-db`.
- [ ] 2.2 Init SQL loads `pgvector` and creates the `aipc`
  database + role.
- [ ] 2.3 `/etc/aipc/memory/backend` defaults to `pgvector`.

## 3. Qdrant (Disabled By Default)

- [ ] 3.1 Quadlet declared but `.disabled` so the bootc + ansible
  renderers skip it.
- [ ] 3.2 Document the `aipc db migrate qdrant` path in
  `db-qdrant/README.md`.

## 4. bge-m3 + Reranker Service

- [ ] 4.1 Quadlet runs a single HTTP service hosting both models.
- [ ] 4.2 Embedding endpoint registered behind LiteLLM's existing
  `embed-bge` alias (Phase 1 already declares it; this change
  supplies the backing service URL).
- [ ] 4.3 Reranker endpoint `/rerank` documented in README.

## 5. RAG Ingest Watchers

- [ ] 5.1 Desktop watcher: poll `~/Desktop` + `~/Documents`,
  diff-index modified files, push chunks to the embedder, write
  vectors to the active backend.
- [ ] 5.2 Code watcher: read repos declared in
  `~/.config/aipc/rag/repos.yaml` (default empty), line-window
  chunking for v1 (Q3 deferred), embed + write.
- [ ] 5.3 Browser watchers: per-browser unit, polls a snapshot
  copy of `places.sqlite` (Firefox) or `History` (Chrome). Gated
  on `/etc/aipc/rag/browser-consent.yaml`.
- [ ] 5.4 Screen+audio watcher: region-selector + TTL'd captures;
  OCR via Lemonade ONNX, audio via Phase 3 Paraformer streaming
  (Q2 — if Phase 3 absent, watcher stays disabled). Gated on
  `/etc/aipc/rag/screen-audio.yaml`. Pauses when
  `aipc-voice-mute.target` active.

## 6. mem0 Server + Wiring

- [ ] 6.1 mem0 service quadlet on port 7000, env points at the
  Postgres backend.
- [ ] 6.2 `LITELLM_BASE_URL=http://127.0.0.1:4000` in the mem0
  service env so its internal LLM calls (summarisation,
  fact-merge) route through the gateway.
- [ ] 6.3 mem0 client config example in README for Phase 4 agents.

## 7. `aipc rag` CLI

- [ ] 7.1 `aipc rag list-sources` — prints the canonical source
  list with state.
- [ ] 7.2 `aipc rag status` — per-source last-cycle timestamp + item
  count + vector count.
- [ ] 7.3 `aipc rag enable <source>` / `disable <source>` — toggles
  the systemd unit and persists consent.
- [ ] 7.4 `aipc rag reindex <source>` — force a full re-index from
  scratch.
- [ ] 7.5 `aipc rag purge <source> [--confirm]` — drop watcher
  vectors; require `--confirm` for irreversible deletes.

## 8. Firstboot Consent Prompts (joint with Phase 7)

- [ ] 8.1 Browser-consent screen contribution: per-browser yes/no,
  writes `/etc/aipc/rag/browser-consent.yaml`.
- [ ] 8.2 Screen+audio consent screen contribution: region
  selector + TTL chooser, writes
  `/etc/aipc/rag/screen-audio.yaml`.
- [ ] 8.3 Hand-off: screens are owned in Phase 2 but rendered by
  the Phase 7 `ops-firstboot` wizard runner.

## 9. Doctor Checks

- [ ] 9.1 `aipc doctor` memory-rag section asserts:
  - Postgres reachable + `pgvector` extension installed.
  - rag-embedder `/healthz` returns 200.
  - mem0 `/healthz` returns 200.
  - Desktop + code watchers active.
  - Active backend matches `/etc/aipc/memory/backend`.
- [ ] 9.2 INFO (not FAIL) checks:
  - Browser watchers status (active when consent recorded).
  - Screen+audio watcher status (active only when opted in).
  - Vector-count threshold warning (suggests `aipc db migrate
    qdrant` if pgvector >1M rows).

## 10. Documentation

- [ ] 10.1 Per-module README for each of the 5 modules.
- [ ] 10.2 `docs/memory-rag.md`: end-to-end diagram + consent gates
  + migration path.
- [ ] 10.3 Confirm `docs/architecture.md §7` Phase 2 row matches
  the 5-module list shipped here (no count change to the §7
  header total).

## 11. Local Build Verification

- [ ] 11.1 Run `tools/aipc render bootc`; confirm Containerfile
  includes the 5 modules (db-qdrant rendered as `.disabled`).
- [ ] 11.2 Run `tools/aipc render ansible --check`; confirm it
  lints clean.
- [ ] 11.3 Run each module's `verify.sh` in a privileged container.

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
