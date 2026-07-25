## ADDED Requirements

### Requirement: Agents snapshot includes peer MCP runs

The portal MUST read the peer MCP event journal read-only and expose folded
peer-run records under `peer_mcp_runs` in `GET /api/v1/agents`. Missing,
unreadable, or malformed journal data MUST be treated as an unavailable
optional source and MUST NOT make the endpoint return HTTP 500.

#### Scenario: Dashboard receives a running peer

- **WHEN** the peer journal contains a running Claude, Codex, or Grok run
- **THEN** `GET /api/v1/agents` includes its stable agent id, peer, status, PID,
  elapsed time, last event time, and bounded output preview

#### Scenario: Peer journal is unavailable

- **WHEN** the peer journal is absent, locked, or unreadable
- **THEN** `GET /api/v1/agents` returns a structured empty `peer_mcp_runs` list
  with optional-source availability information
- **AND** existing delegation, kanban, process, and log fields remain usable

### Requirement: Stale peer runs are reported truthfully

The portal MUST check PID liveness for non-terminal peer journal records. A
non-terminal record whose PID no longer exists MUST be reported as `stale`; the
portal MUST NOT infer success or failure and MUST NOT mutate the journal.

#### Scenario: MCP server disappears during a run

- **WHEN** a journal record is still `running` but its PID is no longer alive
- **THEN** the snapshot reports `status: stale` and preserves the last output
  and timestamps

### Requirement: Agents page renders peer progress

The Agents page MUST render a Peer MCP section using the existing JSON poller.
It MUST show peer, lifecycle state, PID, elapsed time, last event, workdir, and
bounded output or terminal error when present. The page MUST remain read-only.

#### Scenario: Peer run updates during polling

- **WHEN** a peer emits a new output or heartbeat event
- **THEN** the next successful Agents page poll updates the run's state and
  output preview without opening a second transport

#### Scenario: Terminal peer remains inspectable

- **WHEN** a peer finishes, fails, times out, or is stopped
- **THEN** the page retains the terminal row and shows its final status and
  bounded result/error context
