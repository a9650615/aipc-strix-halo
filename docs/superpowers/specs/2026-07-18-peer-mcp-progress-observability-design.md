# Peer MCP Progress Observability Design

## Goal

Make Hermes peer-agent work visible in the existing AI Dashboard for
`ask_claude`, `ask_codex`, `ask_grok`, and `collaborate`, with enough live
information to answer: which peer is running, what process owns it, how long it
has been running, and what it most recently emitted.

This deliberately stops short of token-level streaming and parsing private,
CLI-specific event formats.

## Current gap

The live `peer-agents` MCP server starts a subprocess with `Popen`, stores its
PID in an in-memory registry, and waits on `communicate()`. The portal can see
some peer processes by scanning `/proc`, but the MCP call is not a durable
event and the child process is often not linked to a goal. The existing Agents
page therefore reports presence and completed summaries, not reliable live
progress.

The existing 0019 Agents page remains the UI foundation. This change adds a
peer-MCP event source; it does not replace `hermes-webui`, write to Hermes
databases, or add dashboard-side process control.

## Alternatives considered

### A. Improve portal inference only

Keep scanning processes and logs and add more heuristics. This is the smallest
diff, but it cannot reliably identify an MCP call or expose recent subprocess
output. It would preserve the current false `unknown` cases.

### B. Structured journal plus bounded subprocess capture — chosen

The peer MCP emits a small JSONL event journal and reads stdout/stderr while a
peer runs. The portal folds the journal into current and recent peer runs and
continues using its existing 8-second ETag poller.

This gives reliable lifecycle and output-tail visibility without coupling the
portal to Claude, Codex, or Grok's private event formats. It also works when a
peer is not represented by Hermes `async_delegations`.

### C. Native CLI event adapters

Run each CLI in its structured streaming mode and normalize its tool/token
events. This would provide the richest UI, but the three CLIs expose different
formats and change them independently. It is deferred until lifecycle/output
visibility proves that tool-level detail is necessary.

## Design

### Event journal

The peer MCP writes append-only events to:

```text
~/.hermes/peer-agents/events.jsonl
```

The directory and file are user-readable only. Every event is a single JSON
object with these fields:

```json
{
  "schema": 1,
  "event_id": "uuid",
  "agent_id": "claude-...",
  "peer": "claude",
  "kind": "started|heartbeat|output|finished|failed|stopped",
  "status": "running|completed|failed|stopped|stale",
  "ts": 1784340000.123,
  "pid": 1234,
  "parent_pid": 1200,
  "workdir": "/work/project",
  "elapsed_seconds": 12.4,
  "output_tail": "last bounded output text",
  "exit_code": null,
  "error": null
}
```

The journal never stores the full prompt, environment, command arguments, or
unbounded output. Output is clipped per event and the journal is rotated or
trimmed at a fixed size. `heartbeat` events keep silent but live processes from
looking stale.

### Peer MCP runtime

The existing `_run()` helper becomes the single instrumentation boundary for
all peer tools. It will:

1. allocate the existing `agent_id`;
2. emit `started` after `Popen` succeeds;
3. drain stdout and stderr incrementally into a bounded tail;
4. emit coalesced `output` events plus periodic `heartbeat` events;
5. emit exactly one terminal event for success, non-zero exit, timeout, or
   `stop_agent()`;
6. retain the current `[agent_id=...]` result prefix.

The existing in-memory registry remains useful for `stop_agent()` and process
control. A new `peer_agent_runs` MCP tool exposes folded active/recent journal
state so Hermes can inspect its own peer fleet without going through the
portal.

### Portal aggregation

`aipc_portal.agents` adds a read-only journal reader that folds events by
`agent_id`, keeps the latest state, and returns bounded recent runs. It merges
these records into the existing `/api/v1/agents` response under
`peer_mcp_runs`.

The portal uses journal state as the authoritative identity for MCP runs and
keeps the current `/proc` scan as a liveness fallback. If the journal says a
run is active but its PID no longer exists, the portal reports `stale`; it does
not infer success or failure. Existing Hermes delegation and kanban records
remain unchanged and read-only.

### Dashboard UI

The existing Agents page gets a Peer MCP section with:

- peer and model/provider label;
- lifecycle state;
- PID and elapsed time;
- workdir and bounded goal/output preview;
- last event time;
- terminal result or error when available.

The existing poller remains the transport. No new SSE/WebSocket is needed for
this first useful version.

### Security and failure handling

- Do not persist prompt text, environment variables, auth paths, or full CLI
  commands.
- Scrub control characters and clip output before writing events.
- Use append-only writes with user-only permissions; malformed lines are
  ignored rather than taking down the portal.
- A missing journal, locked file, or unavailable MCP is an empty optional
  source, not an HTTP 500.
- A peer MCP restart leaves old runs in the journal; PID liveness determines
  whether an unfinished run is `stale`.
- The dashboard remains loopback and read-only.

## Verification

Static verification covers the event fold, bounded output, malformed journal
handling, terminal-state rules, and API/UI contracts with fake subprocesses and
JSONL fixtures. Render verification covers both portal targets using the
repository's existing bootc/ansible render checks. Hardware verification is
needed only to prove a real subscription CLI emits events through the live
Hermes MCP configuration.

## Non-goals

- token streaming;
- provider-specific tool-event parsing;
- dashboard-side cancellation or retry;
- replacing hermes-webui;
- modifying Hermes `state.db` or `kanban.db`;
- remote access or new credentials.
