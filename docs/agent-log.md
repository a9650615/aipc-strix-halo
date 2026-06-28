# Agent Log

Append-only chronological record of every agent run on this repo. Lets a 大哥 review who did what and catch unattributed work. See `CLAUDE.md §11` for the schema.

Columns:

- **date** — ISO-8601, the day the run started (Asia/Taipei).
- **role** — 大哥 / 副官 / 執行兵.
- **model** — model id used; if a 大哥 dispatched subagents, list them too (e.g. `opus → sonnet x3`).
- **run label** — matches `Agent-Run:` trailer.
- **spec task(s)** — `<change>#<id>` references; `n/a` for repo-level work.
- **sha range** — `<first-sha>..<last-sha>` of the run's commits.
- **outcome** — one line.

| date | role | model | run label | spec task(s) | sha range | outcome |
|---|---|---|---|---|---|---|
| 2026-06-27 | 大哥 | opus-4.7 | brainstorm-architecture | n/a (pre-spec; produced `docs/architecture.md`) | n/a | 7-phase / 44-module design locked with user |
| 2026-06-27 | 大哥 | opus-4.7 | phase-0-spec-write | phase-0-foundation (all 4 artifacts) | n/a (uncommitted) | proposal + design + spec + tasks written, `openspec validate` passes |
| 2026-06-27 | 副官 x3 | opus → sonnet x3 (parallel) | phase-0-scaffold-modules-cli-bootstrap | phase-0-foundation#1.1-1.5, #3, #4.1-4.10, #5.1-5.4 | 5a57bb6 (initial), tools/+modules/+bootstrap/ci all in | 15 pytests pass, shellcheck+yamllint clean, smoke test green |
| 2026-06-27 | 大哥 | opus-4.7 | phase-0-cli-base-default-fix | phase-0-foundation#4.9 | (rolled into 5a57bb6) | `_DEFAULT_BASE` aligned to `ghcr.io/ublue-os/bazzite-dx:stable` |
| 2026-06-27 | 執行兵 | (out-of-band agent, unattributed) | git-push-and-secrets-setup | phase-0-foundation#1.6, #2.1-2.7 | 5a57bb6..71e58a2..f4e49dc | repo pushed to `a9650615/aipc-strix-halo`; SOPS+age docs written |
| 2026-06-27 | 副官 | (out-of-band agent, unattributed) | phase-1-modules-scaffold (PROTOCOL VIOLATION) | none — was off-spec at the time | ..2f6f6d3 | added 4 llm-* modules **without an OpenSpec change**, retroactively legalised below |
| 2026-06-28 | 大哥 | opus-4.7 | phase-0-build-fix | phase-0-foundation (build green) | 76eb854..4d5f112..546c1b4 | 5-round CI debug: amd-smi drop, sops via upstream binary, COPY post-install pattern, /usr/lib relocation (bootc /usr/local is symlink to /var), kargs.d TOML (bootc has no kargs subcommand). First `ghcr.io/a9650615/aipc:rolling` published. |
| 2026-06-28 | 副官 | sonnet | phase-1-spec-retro | phase-1-ai-runtime (all 4 artifacts) | b7ecd58 | OpenSpec change written to retroactively cover the 4 pre-existing llm-* modules; 5 gap tasks identified (R3 keep-alive, R4 vLLM eviction, R5 models.yaml, R6/R7 ai-rocm/ai-xdna missing, R8 doctor alias check) |
| 2026-06-28 | 大哥 | opus-4.7 | phase-1-modules-disable-gate | n/a (CI un-block) | f47a8c9 | 4 llm-* modules marked `.disabled`; renderer skips them. Removes Phase 1 build-time bugs from Phase 0 image; legit Phase 1 fix work tracked as tasks 1.x. |
| 2026-06-28 | 大哥 | opus-4.7 | claude-md-roles-and-attribution | n/a (process) | (this commit) | CLAUDE.md §0 Roles + §11 Attribution added; this log seeded with prior runs back-filled |
| 2026-06-28 | 副官 | Qwen3.7-max | phase1-lemonade-port-fix-2026-06-28 | phase-1-ai-runtime#1.4 | b3a14ec | verify.sh default port corrected 8000→8001 to match quadlet |
| 2026-06-28 | 副官 | claude-sonnet-4-6 | phase-0-review-fix-2026-06-28 | phase-0-foundation#R4, phase-1-ai-runtime#R3 | cb7b0ec..8e1c61a | ansible renderer kargs parity (TOML copy task replaces bogus bootc subcommand); regression guard added; HSA_OVERRIDE_GFX_VERSION spec typo 11.0.0→11.5.1 |
| 2026-06-28 | 副官 | claude-sonnet-4-6 | claude-md-orchestrator-trailer-2026-06-28 | n/a (repo process) | (this commit) | CLAUDE.md §11: optional Agent-Orchestrator trailer added (template line + explanatory bullet + two examples); dispatched by claude-opus-4-7 |
| 2026-06-28 | 副官 | Qwen3.7-max | phase1-batch-2026-06-28 | phase-1-ai-runtime#1.2,1.3,1.8,1.10,2.1,2.2,2.3,3.1,3.2,3.3,4.1,4.2 | b3c7d58 | 3 new modules (ai-rocm, ai-xdna, llm-models), LiteLLM digest pin + timeout, OLLAMA_KEEP_ALIVE=-1, doctor exit-2→OPTIONAL + gateway alias check, aipc models list/sync --check. 24 tests pass. |
