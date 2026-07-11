## ADDED Requirements

### Requirement: Streaming Voice Turn Worker

The system SHALL provide a streaming voice turn worker that accepts a
completed user utterance (PCM or WAV plus session id) from the wake/PTT
path and produces spoken output by overlapping STT finalization, streaming
LLM tokens, chunked TTS synthesis, and audio playback. The worker SHALL
NOT open a second microphone capture while wake already owns the single
arecord stream for that session.

#### Scenario: Turn completes with streamed speech

- **WHEN** wake delivers a command WAV after end-of-speech and streaming
  mode is enabled
- **THEN** the worker obtains a transcript, streams an LLM reply, synthesises
  at least one TTS audio chunk before the full reply text is complete when
  the model emits a sentence boundary, and plays audio on the primary
  output sink

#### Scenario: Batch fallback on stream failure

- **WHEN** any stream stage fails (STT, LLM SSE, or TTS chunk) for a turn
- **THEN** the system falls back to the existing batch voice-once path for
  that turn and records a stream_fallback outcome in logs

---

### Requirement: Time-to-First-Audio Improvement

The streaming path MUST start audible TTS playback for a short local
question before the full LLM reply text is complete whenever the model
emits a sentence boundary and TTS for that sentence succeeds. For
comparable short turns under normal load with `resident-small` and Kokoro
available, first-audio latency MUST be lower than an equivalent batch turn
that waits for full LLM text before any TTS request. Implementations SHALL
document the measured hardware TTFA when enabling the feature by default.

#### Scenario: First chunk plays before full reply

- **WHEN** the LLM stream emits a complete first sentence and TTS for that
  sentence succeeds
- **THEN** playback of that sentence begins while later tokens may still be
  arriving

---

### Requirement: Partial UX During Stream

The streaming turn SHALL publish shared voice UX states through the existing
`aipc_lib.voice_ux` contract, including partial transcript and/or partial
reply text in the status `partial` or `detail` fields so the overlay can
update without system notification spam.

#### Scenario: Overlay shows thinking partials

- **WHEN** LLM tokens are streaming for a voice turn
- **THEN** UX state is `thinking` or `speaking` as appropriate and the status
  file includes a non-empty partial or detail snippet of the reply so far

---

### Requirement: Barge-In Cancels Playback And Generation

While a streaming turn is in `thinking` or `speaking`, the system SHALL
accept a barge-in signal (user PTT cancel, explicit cancel control, or
configured speech-energy barge). On barge-in the system MUST stop TTS
playback, MUST abort the in-flight LLM stream client, and MUST return the
surface toward `listening` without altering master sink volume.

#### Scenario: User barges during speech

- **WHEN** barge-in is signalled during TTS chunk playback
- **THEN** playback stops within one chunk boundary, no further TTS chunks
  from that turn are started, and master sink volume is unchanged from the
  pre-turn user setting

---

### Requirement: Master Volume Inviolable

Streaming duck, unduck, and TTS playback SHALL NOT change the system master
sink volume level. Ducking SHALL use per-stream sink-input volume only.
TTS stream volume normalization SHALL apply only to the assistant playback
stream.

#### Scenario: Stream turn leaves master volume unchanged

- **WHEN** a full streaming turn runs including duck and multi-chunk TTS
- **THEN** `pactl get-sink-volume @DEFAULT_SINK@` after the turn matches the
  pre-turn user-set level within normal meter noise

---

### Requirement: Feature Flag Default Off Until Hardware-Verified

Streaming mode SHALL be gated by configuration (for example
`AIPC_VOICE_STREAM`) and SHALL default to disabled until a
hardware-verified claim is recorded for the Strix Halo machine. When
disabled, wake SHALL continue to use the batch voice-once path.

#### Scenario: Default path remains batch

- **WHEN** streaming mode is not enabled
- **THEN** end-of-speech still invokes the batch voice-once WAV path and no
  streaming worker is required for a successful turn
