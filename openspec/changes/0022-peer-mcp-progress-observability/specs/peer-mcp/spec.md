## ADDED Requirements

### Requirement: Peer dispatches publish bounded lifecycle events

The peer-agents MCP server MUST publish user-local JSONL events for every
`ask_claude`, `ask_codex`, `ask_grok`, and `collaborate` child run. Events MUST
include a stable `agent_id`, peer name, PID when available, timestamp, status,
and bounded output state. The event stream MUST include a start event and one
terminal event for normal completion, failure, timeout, or explicit stop.

#### Scenario: Peer run starts and completes

- **WHEN** `ask_claude` starts a Claude subprocess and it exits with code 0
- **THEN** the journal contains a `started` event followed by a `finished`
  event for the same `agent_id`
- **AND** the terminal event has `status: completed` and the exit code

#### Scenario: Peer run fails or times out

- **WHEN** a peer subprocess exits non-zero or reaches its timeout
- **THEN** the journal contains one terminal `failed` event with bounded error
  or output context
- **AND** the MCP response retains the existing agent-id prefix

#### Scenario: Peer run is stopped

- **WHEN** `stop_agent(agent_id)` terminates a tracked peer process
- **THEN** the journal contains one terminal `stopped` event for that agent
- **AND** the event records bounded partial output without the full prompt

### Requirement: Peer output is observable without unbounded persistence

The peer-agents MCP server MUST drain stdout and stderr while a peer runs,
publish bounded output/heartbeat updates, and cap or rotate the journal. It MUST
NOT persist full prompts, environment variables, auth paths, or unbounded CLI
output.

#### Scenario: Silent long-running peer remains live

- **WHEN** a peer process emits no output for longer than one output interval
  but remains alive
- **THEN** the journal receives a heartbeat event with the same `agent_id` and
  `status: running`

#### Scenario: Large output is clipped

- **WHEN** a peer emits output larger than the configured event tail limit
- **THEN** each journal event contains only the bounded, control-character-
  scrubbed tail
- **AND** the journal remains below its configured rotation threshold

### Requirement: MCP exposes active and recent peer runs

The peer-agents MCP server MUST expose a `peer_agent_runs` tool that returns
folded active and recent run state from the journal. A missing, malformed, or
unavailable journal MUST produce an empty optional source rather than crash the
MCP server.

#### Scenario: Hermes queries active peer runs

- **WHEN** `peer_agent_runs` is called while a peer is running
- **THEN** the response includes that `agent_id`, peer, PID, status, elapsed
  time, last event time, and output preview

#### Scenario: Journal contains malformed lines

- **WHEN** the journal contains a partial or invalid JSONL line
- **THEN** `peer_agent_runs` skips that line and returns valid neighboring runs
