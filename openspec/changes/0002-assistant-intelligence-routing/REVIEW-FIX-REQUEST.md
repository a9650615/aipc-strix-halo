# Review fix request — `0002-assistant-intelligence-routing`

**For:** Codex (or any 副官 rewriting this OpenSpec change)
**From:** 大哥 review (Grok session, 2026-07-10)
**Scope:** Spec documents only under this directory. **Do not implement product code.**
**Validate when done:**

```bash
npx -y @fission-ai/openspec validate 0002-assistant-intelligence-routing --strict
```

**Touch only:**

- `openspec/changes/0002-assistant-intelligence-routing/proposal.md`
- `openspec/changes/0002-assistant-intelligence-routing/design.md`
- `openspec/changes/0002-assistant-intelligence-routing/tasks.md`
- `openspec/changes/0002-assistant-intelligence-routing/specs/**` (add deltas if required)
- This file may gain a short “Addressed” checklist at the bottom if useful

**Do not:** edit live modules, restart services, or expand scope into adapter implementation.

---

## Verdict (context for the author)

Direction is correct: one `RouteDecision` authority, local-first ladder, paid gates, full-result vs spoken-summary, provider adapters.
`openspec validate --strict` already passes. The problems below are **spec completeness / consistency / live alignment / scope slicing**, not “throw away and rewrite.”

---

## P0 — must fix

### 1. Modified capabilities vs delta specs mismatch

`proposal.md` claims these are modified:

- `voice-pipeline`
- `codexbar-usage`

But `specs/` only has:

- `assistant-intelligence-routing` (new)
- `agent-runtime`
- `ai-runtime`

**Do one of:**

- **A (preferred if voice/spoken_summary and quota-as-input are real requirements of this change):** add
  - `specs/voice-pipeline/spec.md`
  - `specs/codexbar-usage/spec.md`
  with ADDED/MODIFIED requirements + scenarios covering spoken summary ownership, barge-in speech-only cancel, and quota telemetry as advisory input; **or**
- **B:** remove `voice-pipeline` and `codexbar-usage` from proposal “Modified Capabilities”, and in `design.md` Relationship section state which existing change owns those surfaces.

Archive must not drop requirements that only lived in prose.

### 2. Add “Current implementation map” to `design.md`

This change reads like greenfield. Live box already has hot paths that will collide. Add a section that maps **current → target** for at least:

| Current (live / repo) | Target under this change |
|---|---|
| `graphs.plan_dispatch` / classifier / keyword fallback | shadow then single router |
| oneshot Hermes / daily system-message path | local worker adapter stage |
| aggregator “resident-small returned text → stop” | input/source adapter only; no terminal policy |
| grounding / skill-learn / feedback「不对」 | quality gate + learning boundary (not parallel reinvention) |
| dual TTS: agent `_speak_best_effort` vs `aipc-voice-once` / krunner | single TTS owner per entry (see P0.3) |
| `session_id=voice-assistant`, `end_session`, barge-in | session + speech cancel semantics |
| `cloud-llm-fallback` manual-only / no-budget | superseded for assistant traffic only (after archive order) |

For each row: **delete / shadow-then-replace / keep as adapter / out of scope**.

### 3. TTS single-owner + barge-in (requirement, not only design prose)

Add an explicit requirement (in `assistant-intelligence-routing` and/or `voice-pipeline` delta):

- Each user-facing entry has **exactly one TTS owner** for a turn.
  - Voice path (`aipc-voice-once` / stream): client owns TTS.
  - KRunner: client owns TTS when it speaks.
  - Agent-side Hermes/notify TTS only when the client will **not** speak.
- **Barge-in** stops spoken rendering only; does not cancel the underlying task unless the user explicitly cancels the task.
- Cancel/barge paths MUST stop orphan playback (e.g. leftover `paplay` / agent hermes TTS) so two voices cannot overlap.

Motivation: hardware already saw dual Kokoro/paplay streams (`hermes TTS done` + `voice-once spoke reply`).

### 4. Uncensored / no topic-keyword policy gates

In D1 (capability planning) and/or a planning requirement, hard-constrain:

- Deterministic analysis may only label **capability, freshness, risk, data_scope, quality, deadline**.
- It MUST NOT refuse, censor, moralize, or force-downrank by **topic keywords**.
- Classifier/rules MUST NOT reintroduce “sensitive topic → no tools / generic chat” behavior.
- Uncensored local model policy remains; routing chooses capabilities, not content morality.

### 5. Promote `cloud-llm-fallback` conflict resolution to task 0.x

Current task **10.6** is too late.

- Add **0.5** (or renumber): before implementing or archiving 0002’s `ai-runtime` delta, either archive still-valid provisioning parts of `cloud-llm-fallback` or withdraw it and carry complete requirements here.
- **Forbidden:** two long-lived active `ai-runtime` deltas that conflict on manual-only vs automatic escalation.
- Keep 10.x as verification reminder if needed, but 0.x is the gate.

---

## P1 — strongly recommended

### 6. Explicit MVP slices in `proposal.md` + `tasks.md`

| Slice | Delivers | Default |
|---|---|---|
| **A** | TaskEnvelope, shadow planner, unify entries, local ladder, structural quality gates, spoken_summary, route traces | Main delivery of this change |
| **B** | Codex + Claude Code adapters, ask grants, explicit canary only | Gated; not parallel “default on” with A |
| **C** | Automatic subscription / metered escalation | Hardware + separate user approval |

Mark tasks §4–6 (and automatic paid parts of §6–9) as **slice B/C**. Slice A must complete its gates before B implementation is considered in-scope for enablement.

### 7. Latency SLOs are post-baseline adjustable

Keep L0/L1/L2 numbers as targets, but state clearly in design + latency requirement:

- Numbers may be revised after task **0.2** hardware baseline (≥50 tasks).
- Until baseline is recorded, **missing L1 p95 route ≤120 ms or first token ≤900 ms MUST NOT fail the local-unification gate** if task success and no privacy/policy regressions hold.
- Acknowledge live reality: classifier hard-timeout ~3.5s and cold model load can blow first-token budgets.

### 8. Expand replay suite examples in task 9.2

Add at least these anti-cases:

- 「查一下用量」→ must use tools/usage capability; must not invent from chat memory.
- STT garbage + multi-turn follow-up under same `session_id`.
- 「不对」→ feedback path; no dual TTS overlap; does not treat prior bad answer as truth.
- 「用 Claude」/「用 Codex」→ explicit provider override subject to policy; never silently ignored and never bypasses grants.

### 9. Default answers for Open Questions (label “pending user confirmation” if not approved)

If the human has not locked them, keep as open but record **recommended defaults** in design:

1. Interactive paid: `ask` once per task; unattended/background: `deny` until time-bounded grant.
2. Metered hard cap: disabled until configured; when configured, local reservation ledger enforces hard cap (provider limits are defense-in-depth only).
3. Remote data: default scopes = `prompt` only; explicit scoped repo for coding; personal docs/email/calendar/screen/mem0/credentials default **deny**; secrets non-exportable always.

---

## P2 — polish

### 10. Naming note

Directory uses `0002-…` while sibling active changes often use unnumbered slugs. One sentence in proposal is enough (numeric OpenSpec id vs descriptive siblings).

### 11. Hard boundary with `assistant-self-improvement`

Learned routing priors may tune scores only. They MUST NOT widen paid policy, data scopes, or tool grants, and MUST NOT override explicit user provider choice or ExecutionGrant denials.

### 12. Quality gate vs existing `grounding.py`

Structural quality / learnability gates should **evolve or wrap** existing grounding — not invent a second parallel “is this answer real?” stack with different criteria.

---

## Delivery checklist (Codex reports back)

- [ ] `openspec validate 0002-assistant-intelligence-routing --strict` passes
- [ ] Every Modified Capability in proposal has a matching `specs/<cap>/spec.md` (or was removed)
- [ ] `design.md` has Current implementation map + MVP slices A/B/C + TTS owner + uncensored constraint + post-baseline SLO note
- [ ] `tasks.md` has 0.x archive-order gate; B/C tasks labeled and gated
- [ ] No product/module code changes in the same commit/PR as this spec fix (unless human asked separately)
- [ ] Short summary of what changed per P0/P1 item

---

## One-line instruction

> Spec direction is approved; fix **delta alignment, live implementation map, single TTS owner, uncensored boundary, MVP slices, adjustable SLOs, and cloud-llm-fallback archive order**. Do not implement runtime code in this pass.

## Addressed by Codex

- [x] Replaced the nonexistent `voice-pipeline` claim with an owner-aligned
  `voice-streaming` delta; kept codexbar as an advisory supplier, not modified.
- [x] Added current implementation map and replace/keep boundaries.
- [x] Added one TTS owner and separate speech/task cancellation semantics.
- [x] Added typed-policy/no-topic-only down-rank invariant.
- [x] Promoted cloud active-change conflict to task 0.5.
- [x] Added Slice A/B/C gates and replay anti-cases.
- [x] Made latency targets post-baseline adjustable and cold starts explicit.
- [x] Locked learned priors below explicit choice, policy, and grants.
- [x] Required routing to consume the existing grounding verifier outcome.
