# CLAUDE.md — Rules for AI Working in This Repository

This document tells any AI (Claude, OpenCode, Goose, Cline, Aider, Continue.dev, Qwen via Aider/Goose, future local agents) how to make changes to this repo without breaking it. OpenCode reads this file automatically as `AGENTS.md` — no extra config needed.

It is enforced socially — there is no CI gate against AI behaviour today. But the structure of this repo makes deviations easy to spot in review.

---

## 0. Role — Pick One Before Acting

Three roles exist. Pick the one that matches what the user (or your own system prompt) signals; ask if unsure. Roles describe **behaviour**, not models — any model can fill any role; the user decides per session.

| Role | Calls / signals | Job |
|---|---|---|
| **大哥 (Big-Brother / Reviewer)** | "you are 大哥", strategic / review / triage requests, CI-failure root-causing, cross-agent coordination, calling shots between revert vs fix | Review work, find root causes, plan, dispatch, judge. Do NOT do mechanical execution yourself when a 副官/執行兵 can be dispatched. Catch spec drift, hold scope, decide direction. |
| **副官 (Lieutenant / Implementer)** | "you are 副官", TDD-shaped tasks, multi-file but bounded changes, writing tests + implementation in one pass | Execute focused tasks end-to-end with TDD. Touch only the files the task names. Report what was skipped/why. |
| **執行兵 (Soldier / Mechanical)** | "you are 執行兵", single-file edits, boilerplate, renames, docs, doc backfills, file moves | Do exactly what was asked, narrowly. No scope expansion. Report results in one short line. |

**The model knows its own identity from its system prompt**; combine that with the user's signal to pick. If the user gave no signal and your identity does not obviously fit, **ask**.

### 0.1 Model → Default Role

When the user names no role, derive a default from your model tier, then let task shape override:

| Model tier (examples) | Default role | Rationale |
|---|---|---|
| Frontier orchestrators (Claude Fable/Mythos, Opus) | 大哥 | Strongest judgment, most expensive — spend on review, root-causing, dispatch; not mechanical edits |
| Strong implementers (Claude Sonnet, Qwen-max, GLM-4.x, Codex) | 副官 | Reliable multi-file TDD execution against a written task spec |
| Fast/small models (Claude Haiku, local ≤ 14B) | 執行兵 | Single-file, mechanical, low-ambiguity edits only |

Precedence: **user's explicit signal > task shape > model tier**. A Sonnet asked to "review and triage" acts as 大哥 and dispatches; a Fable asked to fix one typo acts as 執行兵 and does it without ceremony.

### 0.2 Dispatch Protocol (大哥 → worker)

1. **大哥 writes a bounded task spec** before dispatching: exact files to touch, `tasks.md` ids served, verification commands to run (and which tier per §9 the worker is expected to reach — most workers have no hardware access and top out at render-verified), and the commit trailer template (including `Agent-Orchestrator:`).
2. **Worker executes only the named files/tasks.** Anything else it discovers goes in the report, not the diff.
3. **Worker commits its own work** with its own model id in `Co-authored-by:` and the dispatching session in `Agent-Orchestrator:` (§11). The 大哥 never commits on a worker's behalf.
4. **Worker reports back**: what was done, what was skipped and why, and which verification tier (§9) was actually reached for each check — not just "passed". State plainly when a claim is render-verified only, so it isn't mistaken for hardware-verified.
5. **大哥 reviews the diff** before it reaches `main`. Branch/worktree merges are the 大哥's job.
6. **Parallel workers must not share files.** If two tasks touch the same file (e.g. `tasks.md`), the 大哥 serializes them or reserves that file for itself.
7. **A worker that hits a spec gap stops and reports** — it does not improvise a design decision. Design decisions belong to the 大哥 or an OpenSpec change.

---

## 1. Read these first

1. `docs/architecture.md` — the long-form source of truth for the project's design (7 phases / 44 modules)
2. `openspec/changes/<change-name>/{proposal,design,specs/**,tasks}.md` for the area you are changing
3. `openspec/specs/<capability>/spec.md` for already-archived requirements

If you cannot find a spec for what you are about to do, **stop and propose a change first** (`npx -y @fission-ai/openspec new change <name>`).

---

## 2. The OpenSpec Loop

All work flows through one of these states: `changes/<id>-…` (propose) → branch work (implement) → user approves (review) → `specs/` updated (archive).

**Never edit `openspec/specs/<capability>/spec.md` directly.** Specs are only updated when a change is archived. If you need new behaviour, write a change proposal:

```
openspec/changes/<NNNN>-<slug>/
├── why.md            # the problem / motivation
├── what.md           # the proposed change (specs/<capability>/spec.md diffs)
├── how.md            # implementation notes
└── tasks.md          # checklist for implementer
```

Increment `<NNNN>` as a zero-padded four-digit number. `0001` is reserved for the Phase 0 foundation.

---

## 3. Module Discipline

The `modules/` directory is the heart of the repo. Every module:

- Has a single purpose stated in its `README.md`.
- Lists its dependencies on other modules.
- Provides `packages.txt`, `files/`, `env/`, `quadlet/`, `post-install.sh`, and `verify.sh` as needed.
- Builds identically when rendered through `targets/bootc/Containerfile` **and** `targets/ansible/site.yml`.

If a change makes the bootc and ansible renders diverge, that is a design error. Fix the module to be neutral, not the renderer to special-case.

**Do not invent new module categories without an OpenSpec change.** The 44 modules in `project.md §7` are exhaustive for v1.

---

## 4. The Two Rendering Targets Stay In Sync

Whenever you touch a module:

1. Run the bootc render (`tools/aipc render bootc`) and confirm it builds.
2. Run the ansible render (`tools/aipc render ansible --check`) and confirm it lints clean.
3. Both must reach the same end state on a clean machine.

If a feature is only achievable on bootc (e.g., kernel-baked driver), explicitly mark the ansible equivalent as `skip-ansible: <reason>` in the module README, and propose the matching capability in an OpenSpec change.

---

## 5. Never Bake Secrets

- `secrets/` contains SOPS-encrypted YAML only.
- Decryption requires the user's age private key, which is **not** in the repo and **never** in CI logs.
- `post-install.sh` and `quadlet/*` may reference `${SOPS_DECRYPTED:foo}` placeholders; the runtime resolves them.
- If you find a plaintext secret anywhere in a diff, refuse the change and flag it.

---

## 6. Hardware Assumptions

Code may assume:

- AMD Ryzen AI MAX+ 395 / Strix Halo APU
- 128 GB unified DDR5X
- Linux kernel ≥ 6.14
- ROCm 7+, gfx1151
- XDNA 2 NPU, amd-xdna driver, Lemonade SDK userspace

Code must **not** assume:

- Discrete GPU presence
- More than one display
- Specific microphone / speaker hardware
- Network connectivity at runtime (every model load must work offline once weights are present)

Any change that breaks these constraints needs an OpenSpec change to widen them.

---

## 7. The LiteLLM Contract

All AI consumers (Pipecat, Continue.dev, Cline, Aider, Goose, OpenCode, Open Interpreter, LangGraph, agent tools, scripts, …) **must** make LLM calls via the LiteLLM gateway at the address declared in `modules/llm-litellm/env/endpoint`.

Reasons:

- A single place to swap engines, route by model name, observe costs, and rate-limit.
- The model namespace (`router-1b`, `intent-3b`, `main-70b`, `coder-fast`, `coder-strong`, `coder-thinking`, `embed-bge`, `vlm-qwen2vl`, …) is the public API surface.
- Adding a new logical model = a LiteLLM config entry, nothing else.

Direct calls to Ollama / Lemonade / vLLM endpoints are allowed only inside the corresponding `modules/llm-*/` itself.

---

## 8. Style Rules When Editing Code

- No comments unless behaviour is non-obvious. The module README is the place for "why".
- No backwards-compatibility shims. The image is rebuilt; there is no installed-base to support.
- Prefer existing patterns in the repo over importing new dependencies.
- Idempotency in `post-install.sh` is mandatory (image rebuilds may re-execute parts during recovery).
- Each `verify.sh` exits non-zero on failure with a one-line diagnosis on stderr.
- `verify.sh` exit codes: `0` = pass, `2` = intentionally disabled/optional (reported as OPTIONAL by `aipc doctor`), any other non-zero = fail.
- **Build-time vs runtime split is mandatory and explicit.** `post-install.sh` runs during image build inside a container with no live services, no GPU/NPU, and no network beyond package repos — it must never `systemctl --now`, `curl` a healthcheck, or otherwise assume a running daemon. Anything that needs the service alive (DB init, model pulls, health checks) belongs in a runtime oneshot unit (`ConditionPathExists` sentinel pattern) or in `verify.sh`, not in `post-install.sh`. This is the most repeated bug class in `docs/agent-log.md` (db-postgres, memory-mem0, rag-embedder, dev-ai-* all hit it) — check it first when a module regresses.

---

## 9. Testing Expectations — Verification Tiers

A verification claim is only as useful as the tier it names. "Passed" or "verified" alone is not enough — say which tier. Real bugs (keep_alive quoting, wrong `HSA_OVERRIDE_GFX_VERSION`, quadlet `Environment`/`Exec` errors, build-time/runtime conflation) have repeatedly shipped past lint + render + pytest green and only surfaced on physical hardware; treat static/render checks as necessary, not sufficient.

| Tier | Who can run it | What it proves | Commands |
|---|---|---|---|
| **Static** | Any model, no hardware needed | Syntax/schema/lint is clean | shellcheck, yamllint, ruff, pytest, `openspec validate --strict` |
| **Render-verified** | Any model, no hardware needed | The module renders correctly into both targets and stays in sync (§4) | `tools/aipc render bootc`, `tools/aipc render ansible --check`, render-parity test |
| **Hardware-verified** | Only a session with access to the physical Strix Halo AI PC | The changed behaviour actually works at runtime — GPU/NPU inference, quadlet startup, real `aipc doctor` output | `bootc switch` + reboot, `aipc doctor`, exercising the specific changed path |

Rules:

- A module moves from `.disabled` to enabled only on a **hardware-verified** claim. Render-verified alone is not sufficient grounds to enable it.
- Most 副官/執行兵 dispatches have no hardware access and top out at render-verified — that's expected, not a shortfall, as long as the report says so plainly (§0.2.4) instead of implying more than was checked.
- There is no VM tier: this repo's hardware assumptions (§6) include GPU/NPU passthrough that a VM cannot exercise meaningfully, so a VM-based bootc-switch check proves boot-only, not the thing that actually breaks. Gate real changes on the physical AI PC instead of a sacrificial VM.
- Do not skip static or render tiers to save time — they're cheap and catch real regressions. If a check is flaky, fix the check or the module — never `|| true`.

---

## 10. When To Stop and Ask the User

Default to making the call yourself, but stop when:

- An OpenSpec change spans more than one capability (cross-cutting).
- A user-visible default would change (voice, models, agent behaviour, gaming UX).
- A new external dependency would need credentials or paid tier.
- A security-sensitive default would loosen (screen-control scope, secret handling, network exposure).

A short message stating the trade-off and your recommendation is enough. Do not ask permission for routine implementation choices the spec already constrains.

---

## 11. Agent Attribution — Every Commit Must Identify Who

Multiple agents (Opus, Sonnet, Qwen via Aider/Goose, future local) work this repo. To make post-hoc review possible, every commit MUST identify the agent and the task it served.

**Commit message trailers (mandatory):**

```
<subject>

<body>

Co-authored-by: <model-id> <noreply@anthropic.com>
Agent-Role: 大哥 | 副官 | 執行兵
Agent-Run: <human-readable run label, e.g. phase-0-build-fix-2026-06-28T07>
Spec-Task: <change-name>#<task-id>   (omit if not tied to a spec task)
Agent-Orchestrator: <orchestrator-id>   (optional; omit when worker and orchestrator are the same)
```

- `Co-authored-by:` is GitHub-recognised; the UI shows the avatar.
- `Agent-Role:` matches §0. Use the role you actually performed in that commit, not your title.
- `Agent-Run:` is a freeform label so multiple commits from the same dispatch can be grouped (`git log --grep "Agent-Run: phase-0-build-fix"`).
- `Spec-Task:` references the OpenSpec change + task id (e.g. `phase-1-ai-runtime#1.3`). If the work falls outside any spec task, omit AND open a change first (see §1 — "stop and propose").
- `Agent-Orchestrator:` When the model named in `Co-authored-by:` was dispatched by a different model or a different Claude Code instance, fill this with a short, greppable identifier of the dispatching session (e.g. `claude-code-instance-A` or `claude-sonnet-4.6/session-B`). Same model + same session: omit.

**Examples:**

```
# same session — omit Agent-Orchestrator:
Co-authored-by: claude-sonnet-4-6 <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: phase-0-review-fix-2026-06-28
Spec-Task: phase-0-foundation#R4

# nested dispatch — fill Agent-Orchestrator:
Co-authored-by: Qwen3.7-max <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: phase1-lemonade-port-fix-2026-06-28
Spec-Task: phase-1-ai-runtime#1.4
Agent-Orchestrator: claude-opus-4-7
```

When a 大哥 (Opus) instructs sonnet/qwen subagents to do work, the **subagent commits the change with its own trailer**. The 大哥 does not commit on the subagent's behalf.

**Aggregated log** lives at `docs/agent-log.md` (append-only). Every agent run logs one row there with date, role, model, run label, task ids, sha range, outcome. Either the agent that did the work appends its row before exiting, or the 大哥 appends on its behalf during review — but it MUST get appended on the same calendar day.

**No trailer = the work is unattributed and a 大哥 must back-fill it before approving the next change.**
