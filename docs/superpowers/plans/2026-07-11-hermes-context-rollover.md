# Hermes Context Rollover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep 128K Hermes sessions usable by bounding tool context and rolling an unrecoverable session into a clean successor with one visible handoff notice.

**Architecture:** Reuse Hermes' existing three-layer tool-result persistence and existing gateway compression-exhaustion reset. Add the missing tail preview and bounded handoff metadata at the shared agent result boundary, then consume it in CLI and gateway session owners without replaying the failed turn.

**Tech Stack:** Python 3.11, pytest, SQLite session store, YAML, OpenSpec.

## Global Constraints

- The local backend context window remains exactly 131,072 tokens.
- Automatic compression begins at `0.70`; the last four messages are protected.
- The local compact auxiliary timeout matches LiteLLM's 600-second request ceiling.
- Complete oversized tool results remain available as local artifacts.
- A rollover never replays model calls, tool calls, or other side effects.
- Use existing Hermes session stores and tool-result storage; add no dependency or daemon.
- Product changes land in `/home/birdyo/.hermes/hermes-agent`; AIPC records the OpenSpec tasks, verification, and live configuration.

---

### Task 1: Preserve head and tail of oversized tool results

**Files:**
- Modify: `/home/birdyo/.hermes/hermes-agent/tools/tool_result_storage.py`
- Test: `/home/birdyo/.hermes/hermes-agent/tests/tools/test_tool_result_storage.py`

**Interfaces:**
- Consumes: `generate_preview(content: str, max_chars: int) -> tuple[str, bool]`
- Produces: the same signature, with a bounded head/omission-marker/tail preview.

- [ ] Add a failing test asserting unique head and tail markers survive while omitted middle text does not.
- [ ] Run `pytest -q tests/tools/test_tool_result_storage.py` and confirm the new assertion fails because only the head is returned.
- [ ] Change `generate_preview` to split `max_chars` between head and tail and preserve the existing unchanged-content path.
- [ ] Run the focused test file and confirm it passes.
- [ ] Commit the Hermes fork change with `Spec-Task: 0005-hermes-context-rollover#1.1,1.2`.

### Task 2: Attach a bounded rollover handoff to exhaustion results

**Files:**
- Create: `/home/birdyo/.hermes/hermes-agent/agent/context_rollover.py`
- Modify: `/home/birdyo/.hermes/hermes-agent/agent/conversation_loop.py`
- Test: `/home/birdyo/.hermes/hermes-agent/tests/agent/test_context_rollover.py`

**Interfaces:**
- Produces: `build_rollover_handoff(messages: list[dict], max_chars: int = 12000) -> str`.
- Produces: exhaustion result key `rollover_handoff: str` while retaining `compression_exhausted: True`.

- [ ] Add failing tests proving the handoff is bounded, contains the latest user goal and artifact paths, and excludes bulky middle output.
- [ ] Run `pytest -q tests/agent/test_context_rollover.py` and confirm import/function failure.
- [ ] Implement the deterministic formatter using only stdlib string handling; do not call another model in the terminal error path.
- [ ] Add the handoff key to both terminal exhaustion returns in `conversation_loop.py`.
- [ ] Run the focused tests and existing compression-progress tests.
- [ ] Commit with `Spec-Task: 0005-hermes-context-rollover#2.1,2.2`.

### Task 3: Persist the handoff into successor sessions

**Files:**
- Modify: `/home/birdyo/.hermes/hermes-agent/gateway/run.py`
- Modify: `/home/birdyo/.hermes/hermes-agent/cli.py`
- Test: `/home/birdyo/.hermes/hermes-agent/tests/gateway/test_35809_auto_reset_clean_context.py`
- Test: `/home/birdyo/.hermes/hermes-agent/tests/cli/test_context_rollover.py`

**Interfaces:**
- Consumes: `agent_result["rollover_handoff"]` and existing `SessionStore.reset_session()` / `HermesCLI.new_session()`.
- Produces: a successor transcript containing one user-visible handoff message and one rollover notice.

- [ ] Add failing gateway and CLI tests proving the old transcript remains, the new session receives only the bounded handoff, and the failed turn is not rerun.
- [ ] Run both focused files and confirm the missing handoff persistence failures.
- [ ] Extend the existing gateway reset block and CLI result boundary to create/reset once and append the handoff; do not invoke `run_conversation` again.
- [ ] Run the focused files plus existing session-reset tests.
- [ ] Commit with `Spec-Task: 0005-hermes-context-rollover#2.1,2.2`.

### Task 4: Apply the approved live configuration

**Files:**
- Modify: `/home/birdyo/.hermes/config.yaml`
- Modify: `/var/home/birdyo/aipc-strix-halo/modules/ccs/README.md`

**Interfaces:**
- Produces: `context_length: 131072`, `compression.threshold: 0.70`, `protect_last_n: 4`, a 600-second compact timeout, and the existing `coder-compact` lane.

- [ ] Update the user YAML without changing provider credentials or unrelated preferences.
- [ ] Parse the YAML and assert the approved values, including `auxiliary.compression.timeout: 600`.
- [ ] Correct the existing Hermes configuration note in `modules/ccs/README.md`.
- [ ] Commit the AIPC documentation with `Spec-Task: 0005-hermes-context-rollover#3.1`.

### Task 5: Verify and record

**Files:**
- Modify: `/var/home/birdyo/aipc-strix-halo/openspec/changes/0005-hermes-context-rollover/tasks.md`
- Modify: `/var/home/birdyo/aipc-strix-halo/docs/agent-log.md`

**Interfaces:**
- Consumes: the completed Hermes commits and live YAML.
- Produces: explicit static, render, and hardware verification claims.

- [ ] Run the focused Hermes tests and `ruff check` on changed Python files.
- [ ] Run `npx -y @fission-ai/openspec validate 0005-hermes-context-rollover --strict`.
- [ ] Run `tools/aipc render bootc`, `tools/aipc render ansible --check`, and render parity tests.
- [ ] Exercise a synthetic protected-tail exhaustion and confirm a successor session receives a bounded handoff without replay.
- [ ] Mark completed task IDs, append the agent log, and commit only the `0005`/log files with required trailers.
