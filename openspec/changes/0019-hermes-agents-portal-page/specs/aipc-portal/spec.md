# Delta — aipc-portal

## ADDED Requirements

### Requirement: Hermes agents management page

The portal SHALL serve a dedicated Agents page at `/agents` (same Control Center
SPA shell as Home and Memory) that displays Hermes-dispatched background work
and peer CLI status.

#### Scenario: Operator opens Agents page

- **WHEN** a user navigates to `http://127.0.0.1:7080/agents`
- **THEN** the portal returns the Agents SPA and the page loads fleet data from
  same-origin `/api/v1/agents`

### Requirement: Agents snapshot API

The portal SHALL expose `GET /api/v1/agents` returning peer readiness, live peer
processes, Hermes async delegations, kanban tasks, and summary counts. When
Hermes home is missing, the response SHALL still be HTTP 200 with empty lists
and an unavailable availability marker.

#### Scenario: Hermes home present

- **WHEN** `~/.hermes/state.db` exists for the resolved primary user
- **THEN** `/api/v1/agents` includes rows from `async_delegations` with id,
  state, goal preview, and timestamps

#### Scenario: Hermes home absent

- **WHEN** no Hermes home can be resolved
- **THEN** `/api/v1/agents` returns HTTP 200 with empty collections and
  `availability` indicating unavailable

### Requirement: Delegation and kanban detail + logs

The portal SHALL expose detail endpoints for a single delegation and a single
kanban task, plus a log-tail endpoint over Hermes agent logs.

#### Scenario: Delegation detail

- **WHEN** a client requests `/api/v1/agents/delegations/{id}` for a known id
- **THEN** the response includes goal, state, tool trace when present, and a
  recent log tail

#### Scenario: Unknown id

- **WHEN** a client requests a non-existent delegation or kanban id
- **THEN** the portal returns HTTP 404
