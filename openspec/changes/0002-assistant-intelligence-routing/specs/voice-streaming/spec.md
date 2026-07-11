# voice-streaming Specification Delta

## MODIFIED Requirements

### Requirement: Barge-In Cancels Playback And Generation

While a turn is speaking, the system SHALL distinguish `speech_cancel` from
`task_cancel`. Barge-in or `speech_cancel` SHALL stop current playback, queued
TTS chunks, and any speech-only summarization stream, but SHALL NOT cancel the
underlying assistant task or discard its canonical full result. A distinct
explicit `task_cancel` SHALL cancel generation/worker execution where the
worker supports cancellation. Both paths SHALL leave the surface ready to
listen and SHALL NOT modify master sink volume.

#### Scenario: User barges during speech

- **WHEN** barge-in is signalled while a task result is being spoken
- **THEN** all playback for that turn SHALL stop, no orphan playback process or
  queued chunk SHALL continue, and the task SHALL remain active unless the user
  explicitly requested task cancellation

#### Scenario: User explicitly cancels task

- **WHEN** the user issues task cancel for an active task
- **THEN** the system SHALL stop speech, propagate cancellation to the worker,
  and preserve a terminal cancellation event in the session

## ADDED Requirements

### Requirement: Exactly One TTS Owner Per Entry

Every user-facing turn SHALL declare exactly one TTS owner. Voice-once or the
voice stream client SHALL own voice-entry TTS; KRunner SHALL own TTS when it
elects to speak; agent-side best-effort TTS MAY run only when the calling client
declares that it will not speak.

#### Scenario: Hermes result returns to voice client

- **WHEN** Hermes produces a result for a voice-owned turn
- **THEN** Hermes SHALL return text/events without starting its own TTS and the
  voice client alone SHALL speak the summary

### Requirement: Spoken Summary Does Not Limit Task Result

Voice presentation SHALL derive a bounded spoken summary from the canonical
full result. TTS-oriented token, sentence, and character limits SHALL NOT cap
the worker's reasoning, artifacts, sources, verification, or stored result.

#### Scenario: Voice task returns a long researched result

- **WHEN** a voice request produces a result longer than the speech limit
- **THEN** the full result SHALL remain available in the session/visual surface
  while only its bounded spoken summary is queued for TTS
