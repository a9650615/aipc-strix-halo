# AGENTS.md — Rules for AI Working in This Repository

This document tells any AI (Claude, Goose, Cline, Aider, Continue.dev, future local agents) how to make changes to this repo without breaking it.

It is enforced socially — there is no CI gate against AI behaviour today. But the structure of this repo makes deviations easy to spot in review.

---

## 1. Read these first

1. `openspec/project.md` — the source of truth for what we are building and why
2. The capability spec under `openspec/specs/<capability>/spec.md` for the area you are changing
3. Any active change in `openspec/changes/` that overlaps your area

If you cannot find a spec for what you are about to do, **stop and propose a change first**.

---

## 2. The OpenSpec Loop

All work flows through one of these states:

```
   propose          implement         review            archive
 ┌─────────┐      ┌──────────┐      ┌────────┐      ┌─────────┐
 │ changes/│ ───▶ │ branch   │ ───▶ │ user   │ ───▶ │ specs/  │
 │ <id>-…  │      │ work     │      │ approves│      │ updated │
 └─────────┘      └──────────┘      └────────┘      └─────────┘
```

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

All AI consumers (Pipecat, Continue.dev, Cline, Aider, Goose, Open Interpreter, LangGraph, agent tools, scripts, …) **must** make LLM calls via the LiteLLM gateway at the address declared in `modules/llm-litellm/env/endpoint`.

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

---

## 9. Testing Expectations

Phase 0 is hardware-verified by the user, not by CI. Once Phase 0 passes, CI gates everything else:

| Layer | Test |
|---|---|
| Per module | `verify.sh` runs in a privileged container; exits 0 |
| Cross-module | `aipc doctor` runs end-to-end; reports all green |
| Image | `bootc switch` to fresh tag on a sacrificial VM succeeds |
| Render parity | bootc image and ansible-applied VM produce identical `aipc doctor` output |

Do not skip these. If a check is flaky, fix the check or the module — never `|| true`.

---

## 10. When To Stop and Ask the User

Default to making the call yourself, but stop when:

- An OpenSpec change spans more than one capability (cross-cutting).
- A user-visible default would change (voice, models, agent behaviour, gaming UX).
- A new external dependency would need credentials or paid tier.
- A security-sensitive default would loosen (screen-control scope, secret handling, network exposure).

A short message stating the trade-off and your recommendation is enough. Do not ask permission for routine implementation choices the spec already constrains.
