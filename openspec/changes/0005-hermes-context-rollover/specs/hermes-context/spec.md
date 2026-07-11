# hermes-context Specification Delta

## ADDED Requirements

### Requirement: Hermes bounds persisted tool context

Hermes SHALL preserve the complete local tool result while placing only a
bounded representation and artifact reference in model context when the result
would consume an excessive prompt share.

#### Scenario: Tool returns oversized output

- **WHEN** a tool result exceeds the configured context contribution limit
- **THEN** the complete result remains available as a local artifact
- **AND** model context receives bounded head/tail content plus its path

### Requirement: Hermes rolls over unrecoverable context

Hermes SHALL create a successor session with a bounded handoff when automatic
compression cannot make the prompt fit. It SHALL notify the user once and keep
the predecessor session available.

#### Scenario: Protected tail cannot be compressed further

- **WHEN** compression cannot produce a prompt within the backend input limit
- **THEN** Hermes creates a new session containing a bounded handoff
- **AND** displays one rollover notice
- **AND** continues a pending user message only if its execution has not begun

#### Scenario: A side effect may already have occurred

- **WHEN** rollover is required after model or tool execution has begun
- **THEN** Hermes SHALL NOT replay the turn or any tool call automatically
- **AND** the handoff records the unresolved state for the next user turn

### Requirement: Hermes uses the real backend context ceiling

Hermes SHALL declare 131,072 tokens for the local coder backend, begin automatic
compression at 70% of usable input, and retain output headroom. Configuration
SHALL NOT advertise a context window larger than the backend provides.

#### Scenario: Local coder backend is configured

- **WHEN** Hermes starts against the local coder backend
- **THEN** its declared context window is 131,072 tokens
- **AND** automatic compression begins at 70% of usable input

### Requirement: Hermes permits local compaction to finish

Hermes SHALL give the local compact auxiliary model up to 600 seconds to
finish a summary, matching the LiteLLM request ceiling.

#### Scenario: A long local summary remains active

- **WHEN** `coder-compact` needs more than an interactive short timeout
- **THEN** Hermes waits up to 600 seconds for the summary
- **AND** it does not abandon the request while Lemonade continues GPU work
