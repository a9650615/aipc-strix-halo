# Hermes Local Delegation and Context Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Hermes run local tools without approval prompts, use Ornith as a neutral technical advisor, and compact long local sessions before the 131K backend limit.

**Architecture:** Hermes keeps the original conversation and invokes Ornith only through a bounded technical-advisor helper that emits a neutral task packet. The Hermes bridge adds the native CLI no-prompt flag. The user-level Hermes configuration reserves output headroom, compacts once at a safe threshold, and uses the existing NPU compact model rather than falling back to the full main context.

**Tech Stack:** Python, Hermes CLI, LiteLLM, Lemonade, unittest, YAML.

## Global Constraints

- All model calls use the local LiteLLM gateway.
- `coder-agentic` and `ornith-35b` remain local aliases with a 131072-token backend window.
- Never export secrets or raw conversation history to the advisor.
- Preserve the live-hotfix loop: repository first, then copy and verify the actual `/var/lib/aipc-agent/` file.
- Static and render verification are required; runtime model verification is hardware-only.

---

### Task 1: Run Hermes local tools without prompts

**Files:**
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/hermes_bridge.py`
- Test: `modules/agent-orchestrator/tests/test_router.py`

- [x] Write a test that asserts the Hermes subprocess command contains both `--accept-hooks` and `--yolo`.
- [x] Run the focused test and confirm it fails because `--yolo` is absent.
- [x] Add `--yolo` alongside `--accept-hooks` in `hermes_bridge.run()`.
- [x] Re-run the focused test and the agent-orchestrator test suite.
- [x] Copy the patched bridge to `/var/lib/aipc-agent/aipc_agent/hermes_bridge.py`, restart `aipc-agent-orchestrator`, and check the service is active.

### Task 2: Delegate neutral technical subtasks to Ornith

**Files:**
- Create: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/technical_advisor.py`
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/hermes_bridge.py`
- Test: `modules/agent-orchestrator/tests/test_router.py`

- [x] Write tests for a neutral packet that retains code/error/config artifacts but excludes original sensitive wording and for an advisor refusal that does not retry.
- [x] Run the tests and confirm they fail because the helper does not exist.
- [x] Implement one helper that calls `ornith-35b` through LiteLLM with only the neutral packet and returns a bounded advisory result.
- [x] Wire it into Hermes only when Hermes identifies a technical task; Hermes remains the final responder.
- [x] Re-run focused tests, then copy and restart the live bridge only after local tests pass.

### Task 3: Keep automatic compaction below the real backend limit

**Files:**
- Modify: `/home/birdyo/.hermes/config.yaml`

- [x] Validate the existing 131072-token declaration and `max_tokens: 8192` output reservation.
- [x] Change `compression.threshold` to `0.65` and `target_ratio` to `0.35`, leaving `protect_last_n: 12` and the local `coder-compact` auxiliary model in place.
- [x] Set the compact auxiliary timeout to 90 seconds so a stalled summary does not block the interactive session for three minutes.
- [x] Confirm YAML parses and calculate the 79.9K trigger below the 122.9K usable input limit; an 80K live soak remains hardware follow-up.

### Task 4: Verify and commit

**Files:**
- Modify: `docs/agent-log.md`

- [ ] Run focused unit tests and `git diff --check`.
- [ ] Render bootc and ansible using the repository CLI module.
- [ ] Record verification tier and any hardware-only limitation in `docs/agent-log.md`.
- [ ] Commit with the required agent trailers.
