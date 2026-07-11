## Why

The local voice closed loop works end-to-end, but every turn is still **batch**:
record full utterance → STT whole WAV → LLM whole reply → TTS whole WAV → play.
Users feel long dead-air after they stop speaking and again before the first
spoken word. Phase 3 already named streaming as a follow-on; the stack is now
stable enough (phrase/PTT wake, single-mic handoff, overlay UX, safe duck, TTS
playback) to promote a **streaming turn** without rewriting the whole agent
runtime.

## What Changes

- Introduce a **streaming voice turn pipeline** that keeps mic frames flowing
  through adaptive end-of-speech, then **overlaps** STT finalization, LLM token
  stream, sentence-chunk TTS, and playback.
- Extend **agent-orchestrator** with a streaming chat surface (SSE or chunked
  HTTP) that still uses LiteLLM aliases only (CLAUDE.md §7); default model
  remains `resident-small` for voice.
- Extend **STT** contract with progressive / final results suitable for a turn
  (partial optional; final required). Prefer SenseVoice for short turns; leave
  room for Paraformer streaming later without blocking S2.
- Extend **TTS** path to **sentence-or-clause chunks**: synthesize and queue
  audio as LLM text arrives; first audio starts before the full reply exists.
- **Barge-in**: user speech (or PTT cancel) stops TTS playback and aborts the
  in-flight turn cleanly.
- Wire **overlay / `aipc_lib.voice_ux`** to `partial` transcript and partial
  reply tokens during the turn.
- Keep **master sink volume inviolable** (duck only other sink-inputs; never
  `set-sink-volume` / raise system loudness).
- **Not in scope**: full always-on duplex conversation graph, ChatGPT online
  path, NPU custom wake ONNX training, or replacing batch `aipc-voice-once` as
  the only fallback (batch remains the degraded path).

## Capabilities

### New Capabilities

- `voice-streaming`: Streaming turn orchestration — frame ingest, end-of-speech,
  partial/final STT, streaming LLM via LiteLLM, chunked TTS playback queue,
  barge-in, and UX partials. Lives beside (and can drive) existing wake/once
  surfaces.

### Modified Capabilities

- `voice` (Phase 3 delta / archive): Turn path upgrades from pure batch
  record→STT→LLM→TTS to streaming-capable turn; batch remains fallback.
- `agent-runtime` (Phase 4): Adds streaming chat response contract for voice
  consumers; non-stream `POST /chat` stays unchanged for text tools.

## Impact

- **Modules (expected)**: `voice-pipecat`, `voice-wake`, `voice-stt-sensevoice`,
  TTS helpers / Kokoro client path, `agent-orchestrator`, `tools/aipc_lib`
  (`voice_ux`, `voice_audio`, CLI).
- **APIs**: new or extended stream endpoints (orchestrator + optional STT);
  LiteLLM streaming completions; no direct engine URLs from consumers.
- **UX**: overlay shows interim transcript / reply; shorter time-to-first-audio.
- **Hard constraints**: offline once weights present; no master volume mutation;
  single-mic ownership during a turn; bootc/ansible module parity.
- **Risk**: partial STT quality, sentence split for Chinese, Kokoro latency per
  chunk — design MUST define fallbacks to batch turn on stream failure.
