# voice-audio-front

## ADDED Requirements

### Requirement: Audio front gate

The system SHALL provide a localhost HTTP gate that accepts short audio
and returns a structured decision without requiring prior STT text.

#### Scenario: Ignore non-speech

- **WHEN** the gate receives audio classified as non-speech or ambient with
  confidence above the ignore threshold
- **THEN** the response `action` is `ignore` and the voice path MUST NOT
  invoke agent-orchestrator for that capture

#### Scenario: Fail soft to STT

- **WHEN** the gate is unreachable, errors, or exceeds its configured
  timeout
- **THEN** the voice path SHALL continue with STT and existing plan_dispatch
  (fail-soft)

#### Scenario: Meaningful speech

- **WHEN** the gate detects speech
- **THEN** `action` is `stt_then_route` or `route` and the closed loop
  continues without user-visible hard failure

### Requirement: No NPU pin theft by default

The default gate implementation SHALL NOT unload or unpin the text
`resident-small` (FLM) model.

### Requirement: Offline default

The default gate SHALL work offline once its weights or heuristic logic
are present on the machine (no cloud required).
