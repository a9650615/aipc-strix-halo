## ADDED Requirements

### Requirement: Per-Turn Latency Record

The voice loop SHALL record, for each completed turn, a machine-readable record
containing the headline monotonic-derived durations `perceived` (user
end-of-speech to first audible output) and `tts_ttfa` (TTS request to first
audio), plus `llm_ttft` (LLM request to first token) when the path produces it.
Marks the path does not produce SHALL be null. The record SHALL be written as
one JSON object per line to
`${XDG_STATE_HOME:-~/.local/state}/aipc-voice/turns.jsonl`.

#### Scenario: Batch turn produces a record

- **WHEN** an `aipc-voice-once` batch turn completes with timing enabled
- **THEN** one JSON line is appended containing a `perceived` duration
- **AND** the streaming-only `llm_ttft` value is present as null without
  causing an error

### Requirement: Turn Path And Scenario Label

Each turn record SHALL carry a small context label: `path` (`batch` or
`stream`), the TTS backend actually used after the fallback chain, and the
active model preset, plus fallback outcome flags. This is to compare a stream
turn against the batch turn it must beat — not to support arbitrary analytics.

#### Scenario: Record labels the path

- **WHEN** a streaming turn and a batch turn run under the same backend and
  preset
- **THEN** each record's `path`, `tts_backend`, and `preset` fields let the two
  be compared directly

### Requirement: No Spoken Content In Records

Turn records SHALL contain only durations and categorical labels. They MUST NOT
contain the user transcript, the LLM reply text, or any other utterance
content.

#### Scenario: Record excludes text

- **WHEN** any turn record is written
- **THEN** it contains no transcript or reply-text field

### Requirement: Best-Effort Non-Blocking Instrumentation

Timing instrumentation SHALL be best-effort: recording MUST NOT fail a turn or
add IO into the per-stage hot path. The record SHALL be written once at turn
end, and any error during that write MUST be swallowed without affecting the
turn result. Instrumentation SHALL be disable-able via the `AIPC_VOICE_TIMING`
environment variable without code changes.

#### Scenario: Log write failure does not break the turn

- **WHEN** the turn-record file cannot be written (e.g. unwritable path)
- **THEN** the voice turn still completes and returns its normal result
- **AND** no exception propagates from the timing recorder

#### Scenario: Instrumentation disabled

- **WHEN** `AIPC_VOICE_TIMING=0` is set
- **THEN** no turn record is written and the turn behaves identically

### Requirement: Bounded Record Log

The turn-record log SHALL be bounded so it cannot grow without limit; the
recorder SHALL retain only the most recent N turns (default configurable) on
write.

#### Scenario: Old records are truncated

- **WHEN** the log already holds N records and a new turn completes
- **THEN** the oldest records are dropped so the file retains at most N records

### Requirement: Minimal Latency Reader Command

The system SHALL provide an `aipc voice timings [--last N] [--json]` command
that reads the turn-record log and prints the most recent N records with a
simple mean of the headline durations. The command SHALL handle an empty or
missing log and malformed lines without crashing. Percentile and per-scenario
breakdown reporting are explicitly out of scope for this capability.

#### Scenario: Recent turns and mean

- **WHEN** an operator runs `aipc voice timings` with recorded turns present
- **THEN** it prints the most recent turns and the mean `perceived` (and other
  available headline durations)

#### Scenario: Empty or malformed log

- **WHEN** the log is missing, empty, or contains malformed lines
- **THEN** the command reports "no data" (or skips bad lines) and exits without
  an error
