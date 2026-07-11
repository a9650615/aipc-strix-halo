## 1. Contracts And Flags

- [ ] 1.1 Freeze SSE event schema (`token`, `done`, `error`, `session_id`) in a short comment block in agent-orchestrator + voice stream client
- [ ] 1.2 Add `AIPC_VOICE_STREAM` (default `0`) and document in `docs/voice-runtime-flow.md`
- [ ] 1.3 Add static tests for event parsing helpers (no hardware)

## 2. Orchestrator Streaming Chat

- [ ] 2.1 Implement streaming chat endpoint on agent-orchestrator via LiteLLM stream (voice session → short voice system prompt)
- [ ] 2.2 Keep non-stream `POST /chat` behaviour and tests green
- [ ] 2.3 Emit explicit terminal error on upstream failure; add unit/integration tests with mocked LiteLLM stream
- [ ] 2.4 Render/module verify: orchestrator `verify.sh` + any new routes documented in module README

## 3. Sentence Chunker And TTS Queue

- [ ] 3.1 Implement token→sentence/clause splitter (Chinese 。！？ and EN .!? + max length safety)
- [ ] 3.2 Implement ordered TTS chunk queue on top of `aipc_voice_tts` (Kokoro-first for stream path)
- [ ] 3.3 Normalize each playback sink-input to 100% stereo; never touch master volume (reuse voice_audio guards)
- [ ] 3.4 Unit tests for splitter and queue ordering / cancel

## 4. Stream Turn Worker

- [ ] 4.1 Add stream worker entry (`aipc-voice-stream` or voice-pipecat stream mode) accepting `--wav` + session id
- [ ] 4.2 Pipeline: STT final → open chat stream → chunk TTS → play; publish UX partials
- [ ] 4.3 On any stage failure: `stream_fallback` → invoke batch `aipc-voice-once --wav`
- [ ] 4.4 Barge-in: cancel player + abort stream client; UX back to listening; master volume unchanged
- [ ] 4.5 Self-test / static verification without mic where possible

## 5. Wake Integration

- [ ] 5.1 Wake end-of-speech submits to stream worker when `AIPC_VOICE_STREAM=1` and worker healthy
- [ ] 5.2 Wake keeps batch once when flag off or worker unhealthy
- [ ] 5.3 Ensure single-mic ownership (worker never opens second arecord for the same turn)
- [ ] 5.4 Wire barge signal from PTT/cancel (and energy if already available without second mic)

## 6. UX And Ops

- [ ] 6.1 Overlay/status: partial transcript/reply during thinking/speaking without notify spam
- [ ] 6.2 `aipc voice status` probes stream flag + worker health
- [ ] 6.3 Update `docs/voice-runtime-flow.md` with stream path diagram and knobs

## 7. Verification Gates

- [ ] 7.1 Static: pytest/ruff/shellcheck for touched modules; `openspec validate voice-streaming-turn --strict` if available
- [ ] 7.2 Render-verified: `tools/aipc render bootc` + `tools/aipc render ansible --check` if module files affect render
- [ ] 7.3 Hardware-verified (physical AI PC only): TTFA vs batch, barge-in, master volume unchanged, offline once weights present
- [ ] 7.4 Only after 7.3: consider defaulting `AIPC_VOICE_STREAM=1` in wake drop-in (separate small commit)
