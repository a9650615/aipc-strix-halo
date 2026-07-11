## ADDED Requirements

### Requirement: Wake Hands Off To Streaming Or Batch Turn

After adaptive end-of-speech command capture, the wake service SHALL hand the
command audio to either the streaming voice turn worker (when streaming mode
is enabled and healthy) or the batch voice-once path (otherwise). Only one
turn handler SHALL process a given command WAV.

#### Scenario: Streaming enabled uses stream worker

- **WHEN** streaming mode is enabled and the stream worker is healthy
- **THEN** wake submits the command WAV to the stream worker rather than only
  batch voice-once

#### Scenario: Streaming disabled uses batch

- **WHEN** streaming mode is disabled
- **THEN** wake submits the command WAV to batch voice-once as today

---

### Requirement: Chunked TTS Playback Queue

The voice TTS path used by streaming turns SHALL accept successive text
chunks for one turn, synthesise each chunk, and play them in order on the
primary sink without requiring the full reply text up front. Master sink
volume SHALL NOT be modified.

#### Scenario: Ordered chunk playback

- **WHEN** two TTS chunks are enqueued for the same turn
- **THEN** the second chunk does not start playback before the first chunk
  finishes or is cancelled by barge-in
