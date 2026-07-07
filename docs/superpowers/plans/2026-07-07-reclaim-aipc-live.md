# Reclaim AIPC_LIVE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-bootstrap option that safely reclaims the Windows-staged `AIPC_LIVE` installer partition into the installed Linux system disk.

**Architecture:** Keep bootstrap shell as a menu/router only. Put planning and execution in a small Python module, exposed through `aipc storage reclaim-live`, with dry-run as the default and a typed confirmation gate for destructive operations.

**Tech Stack:** Bash, Python 3.12, Click, pytest, Linux block-device tools (`findmnt`, `lsblk`, `sfdisk`, `partprobe`, `btrfs`, `xfs_growfs`, `resize2fs`).

## Global Constraints

- Do not touch Windows partitions.
- Do not move partitions or merge non-adjacent free space.
- Real disk changes require `--confirm` and typed phrase `reclaim AIPC_LIVE`.
- Default command mode is dry-run and must not execute destructive commands.
- Verification for this implementation is Static only; real partition reclaim is hardware verification and requires explicit user confirmation.

---

## File Structure

- Create `tools/aipc_lib/storage_reclaim.py`: gather disk state, build a reclaim plan, print it, and execute only after confirmation.
- Create `tools/tests/test_storage_reclaim.py`: minimal guardrail tests for absent/duplicate/different-disk/not-adjacent/valid plans and dry-run executor behavior.
- Modify `tools/aipc_lib/cli.py`: add `aipc storage reclaim-live` command.
- Modify `install-aipc-linux.sh`: add guided menu option that calls `aipc storage reclaim-live`.

---

### Task 1: Add storage reclaim planner

**Files:**
- Create: `tools/aipc_lib/storage_reclaim.py`
- Test: `tools/tests/test_storage_reclaim.py`

**Interfaces:**
- Produces: `Plan`, `PlanStep`, `build_plan(lsblk: dict, root_source: str, root_fstype: str) -> Plan`, `format_plan(plan: Plan) -> str`, `run_reclaim(confirm: bool, input_func=input, runner=subprocess.run) -> int`
- Consumes: no project internals.

- [ ] **Step 1: Write the failing planner tests**

Create `tools/tests/test_storage_reclaim.py` with tests for missing/duplicate/different-disk/not-adjacent/valid plan and dry-run no-op execution.

- [ ] **Step 2: Run planner tests and verify failure**

Run: `pytest tools/tests/test_storage_reclaim.py -q`
Expected: import failure for `aipc_lib.storage_reclaim`.

- [ ] **Step 3: Implement minimal planner/executor**

Create `tools/aipc_lib/storage_reclaim.py`. Use dataclasses. Use `lsblk -J -O`, `findmnt -no SOURCE /`, and `findmnt -no FSTYPE /` for live data. Refuse unsafe plans by returning `Plan(allowed=False, reason=...)`. Only `execute_plan()` may run destructive commands, and only after `run_reclaim(confirm=True)` receives typed phrase `reclaim AIPC_LIVE`.

- [ ] **Step 4: Run planner tests and verify pass**

Run: `pytest tools/tests/test_storage_reclaim.py -q`
Expected: PASS.

---

### Task 2: Wire CLI command

**Files:**
- Modify: `tools/aipc_lib/cli.py`
- Test: `tools/tests/test_storage_reclaim.py`

**Interfaces:**
- Consumes: `storage_reclaim.run_reclaim(confirm: bool) -> int`
- Produces: Click command `aipc storage reclaim-live [--confirm]`.

- [ ] **Step 1: Add CLI coverage**

Extend `tools/tests/test_storage_reclaim.py` with `CliRunner` coverage that invokes `storage reclaim-live` and asserts the dry-run path exits through `storage_reclaim.run_reclaim(confirm=False)`.

- [ ] **Step 2: Run the CLI test and verify failure**

Run: `pytest tools/tests/test_storage_reclaim.py -q`
Expected: command does not exist or monkeypatch target is unused.

- [ ] **Step 3: Add the command**

In `tools/aipc_lib/cli.py`, import `storage_reclaim as storage_reclaim_mod`, add `@main.group("storage")`, and add `storage reclaim-live --confirm` that exits with the return code from `run_reclaim()`.

- [ ] **Step 4: Run the CLI test and verify pass**

Run: `pytest tools/tests/test_storage_reclaim.py -q`
Expected: PASS.

---

### Task 3: Add first-bootstrap menu option

**Files:**
- Modify: `install-aipc-linux.sh`

**Interfaces:**
- Consumes: CLI command `aipc storage reclaim-live`.
- Produces: guided menu option for read-only reclaim dry-run.

- [ ] **Step 1: Update menu text**

Change menu to include:

```text
[4] Reclaim AIPC_LIVE into system disk (dry-run)
[5] Show recovery/debug info
```

- [ ] **Step 2: Add menu case**

Add case `4)` that prints a short note and runs `aipc storage reclaim-live`; move recovery to case `5)`.

- [ ] **Step 3: Syntax-check shell**

Run: `bash -n install-aipc-linux.sh`
Expected: no output and exit 0.

---

### Task 4: Verify static behavior

**Files:**
- Modify as needed only if tests fail: `tools/aipc_lib/storage_reclaim.py`, `tools/aipc_lib/cli.py`, `install-aipc-linux.sh`, `tools/tests/test_storage_reclaim.py`

**Interfaces:**
- Consumes all previous tasks.
- Produces static verification evidence.

- [ ] **Step 1: Run focused tests**

Run: `pytest tools/tests/test_storage_reclaim.py -q`
Expected: PASS.

- [ ] **Step 2: Run shell syntax check**

Run: `bash -n install-aipc-linux.sh`
Expected: PASS.

- [ ] **Step 3: Report verification tier**

Report Static verification only. Do not claim hardware verification unless the user explicitly runs the destructive flow on the machine.
