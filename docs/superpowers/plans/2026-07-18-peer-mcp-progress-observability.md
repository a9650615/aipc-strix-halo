# Peer MCP Progress Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ask_claude`, `ask_codex`, `ask_grok`, and `collaborate` visible in the existing Agents dashboard with reliable lifecycle, PID, elapsed-time, and bounded recent-output state.

**Architecture:** The live peer MCP keeps process ownership but emits bounded JSONL lifecycle events from its shared `_run()` boundary. A small stdlib event-contract helper is kept in the repo and copied beside the live user-home MCP during the documented runtime sync. The portal folds the journal read-only into `/api/v1/agents`; the existing 8-second ETag poller renders it without a second transport.

**Tech Stack:** Python 3 stdlib (`json`, `os`, `select`, `subprocess`, `threading` only where required), existing portal Python server, Astro, existing pytest, existing bootc/ansible render tooling.

## Global Constraints

- All peer calls continue using the existing subscription-backed CLI paths; no API-key provider or new credential is added.
- The journal contains no full prompt, environment, auth path, complete command, or unbounded output.
- Portal access remains loopback-only, read-only, and tolerant of missing/malformed optional state.
- No token-level streaming or provider-specific Claude/Codex/Grok event parser is introduced.
- Existing `[agent_id=...]` MCP response prefixes and `stop_agent()` behavior remain intact.
- Build-time scripts do not access the live user home or start services; live sync is an explicit runtime/hotfix action.
- Existing uncommitted user files are out of scope and must not be staged.
- Verification claims name their tier: static, render-verified, or hardware-verified.

---

## File Map

### New files

- `tools/aipc_lib/peer_mcp_events.py` — repo-owned stdlib event schema, bounded writer, fold helper, and PID liveness helper; copied beside the live MCP as a runtime artifact.
- `tools/tests/test_peer_mcp_events.py` — red/green tests for clipping, journal folding, malformed lines, terminal states, and stale PID behavior.

### Modify in the repository

- `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/agents.py` — read-only peer journal aggregation into the existing fleet snapshot.
- `tools/tests/test_portal_agents.py` — JSONL fixtures and `/api/v1/agents` assertions.
- `modules/system-aipc-portal/web/src/pages/agents.astro` — Peer MCP rows/detail rendering and data model.
- `modules/system-aipc-portal/web/src/scripts/i18n.js` — labels for Peer MCP state and fields.
- `modules/system-aipc-portal/README.md` — endpoint/data-source contract.
- `modules/system-aipc-portal/files/usr/lib/aipc-portal/static/` — generated Astro output after the web build.
- `modules/agent-mcp-gateway/README.md` — document the peer event contract and explicit runtime sync boundary.
- `docs/live-hotfix-workflow.md` — backup, copy, py_compile, and rollback steps for the user-home MCP file and helper.
- `openspec/changes/0022-peer-mcp-progress-observability/tasks.md` — mark only completed tasks after evidence exists.
- `docs/agent-log.md` — append the required same-day run record at handoff.

### Modify only as a live runtime target

- `/home/birdyo/.hermes/mcp/peer-agents/server.py` — integrate the event helper, stream bounded stdout/stderr, emit heartbeat/terminal events, add `peer_agent_runs`, and preserve ask/stop contracts. This path is outside the repository and is never staged as repository source.
- `/home/birdyo/.hermes/mcp/peer-agents/peer_mcp_events.py` — runtime copy of `tools/aipc_lib/peer_mcp_events.py`.
- `/home/birdyo/.hermes/peer-agents/events.jsonl` — runtime event journal created with user-only permissions.

---

### Task 1: Define and test the event contract

**Files:**
- Create: `tools/aipc_lib/peer_mcp_events.py`
- Test: `tools/tests/test_peer_mcp_events.py`

**Interfaces:**
- `append_event(hermes_home: Path, event: dict[str, Any]) -> dict[str, Any]` creates `~/.hermes/peer-agents/events.jsonl`, appends one JSON object, and returns the sanitized event.
- `fold_events(path: Path, limit: int = 100) -> list[dict[str, Any]]` returns the newest folded run records keyed by `agent_id`, skipping malformed/partial lines.
- `clip_output(value: object, limit: int = 4000) -> str` removes control characters except newline/tab and returns a bounded tail.
- `pid_alive(pid: object) -> bool` uses `os.kill(pid, 0)` and returns false for invalid/dead PIDs without raising.
- `terminal_status(kind: str, exit_code: int | None = None) -> str` maps terminal event kinds to `completed`, `failed`, or `stopped`.

- [ ] **Step 1: Write the failing tests for output safety and schema.**

```python
def test_clip_output_scrubs_controls_and_keeps_tail() -> None:
    value = "old\x00\x1b[31mnew\n" + ("x" * 20)
    assert clip_output(value, limit=12) == "xxxxxxxxxxx…"


def test_append_event_creates_user_only_jsonl(tmp_path: Path) -> None:
    event = append_event(tmp_path / ".hermes", {
        "agent_id": "claude-1",
        "peer": "claude",
        "kind": "started",
        "status": "running",
        "pid": 123,
    })
    assert event["schema"] == 1
    path = tmp_path / ".hermes" / "peer-agents" / "events.jsonl"
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
```

- [ ] **Step 2: Run the focused tests and verify the correct RED failure.**

Run: `pytest tools/tests/test_peer_mcp_events.py -q`

Expected: FAIL because `tools.aipc_lib.peer_mcp_events` and its functions do not exist yet.

- [ ] **Step 3: Implement the smallest stdlib-only contract.**

Use a fixed `MAX_OUTPUT_CHARS = 4000`, `MAX_JOURNAL_BYTES = 5_000_000`,
`os.makedirs(..., mode=0o700, exist_ok=True)`, `os.open(..., O_APPEND|O_CREAT|O_WRONLY, 0o600)`, and a final newline per event. `fold_events()` must preserve the latest event fields per agent, retain `output_tail`, and sort by `ts` descending.

- [ ] **Step 4: Add the folding and stale-state tests.**

```python
def test_fold_events_skips_bad_lines_and_keeps_latest(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"agent_id":"a","peer":"codex","kind":"started","status":"running","ts":1,"pid":99}\n'
        'not-json\n'
        '{"agent_id":"a","kind":"output","status":"running","ts":2,"pid":99,"output_tail":"Read file"}\n'
        '{"agent_id":"b","kind":"finished","status":"completed","ts":3,"pid":100}\n',
        encoding="utf-8",
    )
    rows = fold_events(path)
    assert [row["agent_id"] for row in rows] == ["b", "a"]
    assert rows[1]["output_tail"] == "Read file"


def test_terminal_status_maps_stop_and_nonzero() -> None:
    assert terminal_status("stopped") == "stopped"
    assert terminal_status("finished", 0) == "completed"
    assert terminal_status("finished", 1) == "failed"
```

- [ ] **Step 5: Run the focused tests and verify GREEN.**

Run: `pytest tools/tests/test_peer_mcp_events.py -q`

Expected: all event-contract tests pass with no new warnings.

- [ ] **Step 6: Commit the contract helper and tests.**

```bash
git add tools/aipc_lib/peer_mcp_events.py tools/tests/test_peer_mcp_events.py
git commit -m "feat: add peer MCP event contract" -m "Co-authored-by: Codex-gpt-5 <noreply@anthropic.com>" -m "Agent-Role: 副官" -m "Agent-Run: peer-mcp-progress-observability-2026-07-18" -m "Spec-Task: 0022-peer-mcp-progress-observability#1.1"
```

### Task 2: Instrument the live peer MCP runner

**Files:**
- Modify live: `/home/birdyo/.hermes/mcp/peer-agents/server.py`
- Copy runtime helper: `/home/birdyo/.hermes/mcp/peer-agents/peer_mcp_events.py`
- Runtime output: `/home/birdyo/.hermes/peer-agents/events.jsonl`
- Verify only: `python3 -m py_compile /home/birdyo/.hermes/mcp/peer-agents/server.py /home/birdyo/.hermes/mcp/peer-agents/peer_mcp_events.py`

**Interfaces:**
- `_run()` emits `started`, coalesced `output`, periodic `heartbeat`, and exactly one terminal event for each `agent_id`.
- `peer_agent_runs(limit: int = 50) -> str` returns JSON with `active` and `recent` folded rows.
- `ask_claude`, `ask_codex`, `ask_grok`, `_call_peer`, `collaborate`, and `stop_agent` retain their current public arguments and result prefix.

- [ ] **Step 1: Copy the tested helper to a temporary runtime path and run its contract tests against that copy.**

Run: `install -m 0644 tools/aipc_lib/peer_mcp_events.py /tmp/peer_mcp_events.py && python3 -m py_compile /tmp/peer_mcp_events.py`

Expected: exit 0; no user-home file is changed during this step.

- [ ] **Step 2: Add a failing live-run smoke harness before editing `_run()`.**

Use the existing live server module in the Hermes Python environment and call `_run([sys.executable, "-c", "print('hello'); time.sleep(.2)"], cwd=tmp_path, timeout=5, agent_id="test-...")`; assert the folded journal contains `started`, an output tail containing `hello`, and `completed`. The harness must also cover non-zero exit and timeout. Run it once and record the expected RED failure in the run log.

- [ ] **Step 3: Replace `communicate()` with bounded incremental pipe draining.**

Use POSIX `selectors.DefaultSelector` over stdout/stderr, maintain a bounded deque/string tail, and flush an `output` event at most every 250 ms. Emit a heartbeat every 5 seconds while the process is alive. Keep `start_new_session=True`, preserve process-group stop behavior, and ensure timeout/stop paths close pipes and emit only one terminal event.

- [ ] **Step 4: Add `peer_agent_runs` and wire every public dispatch path through the same journal.**

The tool returns JSON only; it must not run a peer or quota probe. `collaborate` keeps its existing per-peer IDs and fan-in result but each child gets independent journal events.

- [ ] **Step 5: Deploy the live helper/server patch using the documented backup/copy loop.**

Back up the live server, copy the tested helper beside it, apply the narrow server edit, run `py_compile`, then use a fake local subprocess smoke test. Do not call a real subscription peer in this step.

- [ ] **Step 6: Verify the live smoke harness turns GREEN and inspect the event file for secrets.**

Expected: lifecycle events appear, bounded output is visible before process completion, timeout/stop statuses are truthful, and no prompt/auth/environment text is persisted.

### Task 3: Add portal aggregation and API coverage

**Files:**
- Modify: `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/agents.py`
- Test: `tools/tests/test_portal_agents.py`
- Modify: `modules/system-aipc-portal/README.md`

**Interfaces:**
- `peer_mcp_runs(hermes: Path | None, limit: int = 100) -> dict[str, Any]` returns `{availability, runs}` and never raises for missing/malformed files.
- `agents_snapshot()` adds `peer_mcp_runs` while preserving all existing keys.

- [ ] **Step 1: Add failing fixture/tests for a running peer and malformed journal.**

```python
def test_agents_snapshot_includes_peer_mcp_runs(tmp_path: Path) -> None:
    hermes = _mk_hermes(tmp_path / "u")
    event_dir = hermes / "peer-agents"
    event_dir.mkdir()
    (event_dir / "events.jsonl").write_text(
        '{"schema":1,"agent_id":"claude-1","peer":"claude","kind":"output",'
        '"status":"running","ts":2,"pid":1,"output_tail":"Reading files"}\n',
        encoding="utf-8",
    )
    snap = agents.agents_snapshot(hermes=hermes, proc_root=tmp_path / "emptyproc")
    assert snap["peer_mcp_runs"]["availability"] == "available"
    assert snap["peer_mcp_runs"]["runs"][0]["agent_id"] == "claude-1"


def test_missing_peer_mcp_journal_is_optional(tmp_path: Path) -> None:
    snap = agents.agents_snapshot(hermes=tmp_path / "nope", proc_root=tmp_path / "emptyproc")
    assert snap["peer_mcp_runs"]["availability"] == "unavailable"
    assert snap["peer_mcp_runs"]["runs"] == []
```

- [ ] **Step 2: Run the focused portal test and verify RED.**

Run: `pytest tools/tests/test_portal_agents.py -q`

Expected: FAIL because `peer_mcp_runs` and the new snapshot key are absent.

- [ ] **Step 3: Implement the read-only journal reader in `agents.py`.**

Read at most the fixed tail needed for the configured limit, skip malformed lines, fold by `agent_id`, and use the existing process-root injection pattern for PID liveness tests. Mark a non-terminal dead PID as `stale`; never rewrite the journal.

- [ ] **Step 4: Add API contract assertions.**

Extend `test_portal_agents_api_routes` to assert `/api/v1/agents` includes `peer_mcp_runs`, its availability, and the bounded run fields. Keep the existing delegation/kanban/log route assertions unchanged.

- [ ] **Step 5: Run the portal tests and verify GREEN.**

Run: `pytest tools/tests/test_portal_agents.py -q`

Expected: all existing and new portal tests pass.

- [ ] **Step 6: Document the new response field.**

Add `GET /api/v1/agents` → `peer_mcp_runs` to `modules/system-aipc-portal/README.md`, including unavailable/stale semantics and the journal path.

- [ ] **Step 7: Commit the portal aggregation.**

```bash
git add modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/agents.py tools/tests/test_portal_agents.py modules/system-aipc-portal/README.md
git commit -m "feat: expose peer MCP runs in portal agents" -m "Co-authored-by: Codex-gpt-5 <noreply@anthropic.com>" -m "Agent-Role: 副官" -m "Agent-Run: peer-mcp-progress-observability-2026-07-18" -m "Spec-Task: 0022-peer-mcp-progress-observability#1.4"
```

### Task 4: Render Peer MCP progress in the dashboard and verify both targets

**Files:**
- Modify: `modules/system-aipc-portal/web/src/pages/agents.astro`
- Modify: `modules/system-aipc-portal/web/src/scripts/i18n.js`
- Generate: `modules/system-aipc-portal/files/usr/lib/aipc-portal/static/`
- Modify: `docs/live-hotfix-workflow.md`
- Modify: `modules/agent-mcp-gateway/README.md`
- Modify: `openspec/changes/0022-peer-mcp-progress-observability/tasks.md`
- Modify: `docs/agent-log.md`

**Interfaces:**
- `applyAgents(data)` reads `data.peer_mcp_runs.runs || []`.
- `renderList()` adds rows with keys `peer:<agent_id>` and tab `peer`.
- Selecting a peer row renders its peer, status, PID, elapsed time, last event, workdir, output tail, and error/result without a mutating request.

- [ ] **Step 1: Add the SPA contract test before changing UI code.**

Extend the existing portal SPA contract test or add the smallest test under `tools/tests/` that reads `agents.astro` and asserts it contains `peer_mcp_runs`, `peer:`, `output_tail`, and `stale` labels. Run it and verify RED.

- [ ] **Step 2: Add the Peer MCP data path and row rendering.**

Keep the existing list/detail layout: add `peer_mcp_runs` to `cache`, normalize each row into the same `items` array, rank running/stale/terminal states using the existing `stateKey`, and render a detail panel from the snapshot record without a new endpoint.

- [ ] **Step 3: Add concise translated labels and state names.**

Add only the keys used by the new rows/detail (`agents.peer_mcp`, `agents.peer`, `agents.output`, `agents.last_event`, `agents.stale`, and the matching state labels) to the existing i18n tables. Do not add a second translation system.

- [ ] **Step 4: Build the Astro page and update shipped static assets.**

Run: `cd modules/system-aipc-portal/web && npm run build`

Expected: exit 0. Copy the generated `dist/` contents into `modules/system-aipc-portal/files/usr/lib/aipc-portal/static/` using the module's existing static-build pattern.

- [ ] **Step 5: Run static tests and verify GREEN.**

Run: `pytest tools/tests/test_portal_agents.py tools/tests/test_portal_i18n_state.py -q`

Expected: all focused portal/API/i18n tests pass.

- [ ] **Step 6: Document deployment and verification tiers.**

Add the live MCP backup/copy/rollback commands to `docs/live-hotfix-workflow.md`; document that the event journal is runtime user state and actual subscription peer execution is hardware/runtime verification. Update `agent-mcp-gateway/README.md` with the event path/schema and no-secret rule. Mark completed OpenSpec tasks only after their corresponding command has passed. Append one `docs/agent-log.md` row with the commit SHA range and static/render/hardware tier.

- [ ] **Step 7: Run full required verification before claiming completion.**

Run each command freshly:

```bash
python3 -m py_compile tools/aipc_lib/peer_mcp_events.py modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/agents.py
pytest tools/tests/test_peer_mcp_events.py tools/tests/test_portal_agents.py tools/tests/test_portal_i18n_state.py -q
npx -y @fission-ai/openspec validate 0022-peer-mcp-progress-observability --strict
tools/aipc render bootc
tools/aipc render ansible --check
```

Expected: each command exits 0; report static and render-verified separately. Do not claim hardware-verified unless a physical Strix Halo run exercises a real peer MCP call.

- [ ] **Step 8: Commit the UI/docs/render artifacts with trailers.**

```bash
git add modules/system-aipc-portal/web/src/pages/agents.astro modules/system-aipc-portal/web/src/scripts/i18n.js modules/system-aipc-portal/files/usr/lib/aipc-portal/static modules/agent-mcp-gateway/README.md docs/live-hotfix-workflow.md openspec/changes/0022-peer-mcp-progress-observability/tasks.md docs/agent-log.md
git commit -m "feat: show peer MCP progress in dashboard" -m "Co-authored-by: Codex-gpt-5 <noreply@anthropic.com>" -m "Agent-Role: 副官" -m "Agent-Run: peer-mcp-progress-observability-2026-07-18" -m "Spec-Task: 0022-peer-mcp-progress-observability#1.5-1.7"
```

## Plan self-review

- Spec coverage: peer lifecycle/output/stop behavior is Task 1–2; portal
  aggregation and stale handling is Task 3; UI, deployment, and verification
  are Task 4.
- Placeholder scan: no deferred implementation step is required; all commands
  and target files are named.
- Type consistency: the event helper returns folded rows keyed by `agent_id`,
  the live MCP exposes those rows as `active`/`recent`, and the portal exposes
  them under `peer_mcp_runs.runs`; the UI consumes that exact path.
- Scope safety: no existing dirty file is included unless explicitly listed in
  the file map, and the live MCP path is never staged as repository content.
