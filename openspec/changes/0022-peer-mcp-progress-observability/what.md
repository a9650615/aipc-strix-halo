# What — peer-mcp-progress-observability

## Scope

### Peer MCP runtime

- Add a user-only JSONL event journal at
  `~/.hermes/peer-agents/events.jsonl`.
- Instrument the shared subprocess runner used by all peer MCP tools with
  `started`, `heartbeat`, `output`, and terminal events.
- Capture a bounded stdout/stderr tail while the process runs.
- Add `peer_agent_runs` for active/recent folded run state.
- Preserve the existing `[agent_id=...]` result contract and `stop_agent`
  behavior.

### Portal backend and UI

- Read and fold the peer MCP journal without writing to Hermes databases.
- Add `peer_mcp_runs` to `GET /api/v1/agents`.
- Render a Peer MCP section showing peer, state, PID, elapsed time, last event,
  workdir, output preview, and terminal error/result.
- Mark unfinished journal records with dead PIDs as `stale`.

### Repository and deployment

- Add the event contract and tests to the repository's agent/portal sources.
- Keep the live user-home MCP deployment explicit; do not bake credentials or
  user-home state into the image.
- Record the runtime sync/live-hotfix step so the next image rebuild does not
  silently lose the MCP instrumentation.

## Out of scope

- Token-level streaming.
- Provider-specific Claude/Codex/Grok event adapters.
- Dashboard cancellation, retry, or mutation of Hermes databases.
- Remote access, new credentials, or replacing hermes-webui.
