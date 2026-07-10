# memory-rag (delta)

## ADDED Requirements

### Requirement: Continuous infer writes

The mem0 HTTP client used by agent-orchestrator SHALL support:

- Asynchronous writes with `infer=true`
- A dedicated long timeout for infer (distinct from short voice search timeout)
- Optional mirroring of tool-lane memories into the chat lane for voice recall

#### Scenario: Infer does not use voice search wall

- **WHEN** a write is issued with `infer=true`
- **THEN** the client SHALL use the infer timeout (default ≥ 60s), not the ≤2s voice search timeout

### Requirement: Consolidation pass

The system SHALL be able to submit a consolidation payload derived from recent short-term dialogue so mem0 can extract durable facts.

#### Scenario: Periodic consolidate

- **WHEN** a session accumulates N successful turns (configured, default 4)
- **THEN** a consolidation pass is enqueued without blocking the user-facing reply
