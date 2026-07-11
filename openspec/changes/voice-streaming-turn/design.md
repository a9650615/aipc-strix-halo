## Context

Today’s closed loop (hardware-verified on Strix Halo) is **turn-batch**:

```text
PTT / phrase wake → single arecord command VAD → WAV
  → aipc-voice-once --wav
  → SenseVoice /transcribe (full)
  → POST :4100/chat (full)
  → Kokoro/Cosy full WAV → paplay
```

Strengths: simple failure domains, single mic ownership, overlay + duck
working, master volume hard-blocked.

Weaknesses: time-to-first-audio = STT + LLM + TTS sum; silence after user
stops is pure wait; no partial UX during think/speak.

Constraints (immutable for this change):

- LiteLLM-only LLM access for consumers (CLAUDE.md §7).
- Offline once weights present; no cloud required for local path.
- Never change master sink volume; duck only sink-inputs with fade.
- Single microphone capture owner per turn (no dual arecord).
- Module renders stay bootc/ansible-neutral.

## Goals / Non-Goals

**Goals:**

- Cut **time-to-first-audio** for local voice turns via overlapped STT/LLM/TTS.
- Stream **LLM tokens** into sentence/clause **TTS chunks** and play as ready.
- Show **partial** transcript/reply on the shared UX overlay.
- Support **barge-in** (stop TTS + cancel turn) from energy/PTT.
- Keep **batch once** as automatic fallback when any stream stage fails.
- Stay local-first on `resident-small` for voice.

**Non-Goals:**

- Full always-on duplex “conversation forever” graph (S3).
- ChatGPT online / Path B (separate change).
- Replacing phrase wake with custom ONNX wake training.
- Streaming STT for multi-minute dictation (Paraformer path deferred).
- Pipecat-ai mandatory rewrite of the entire stack (optional adapter later).

## Decisions

### D1 — Streaming turn worker, not rewrite of wake

**Choice:** Keep `aipc-voice-wake` as entry (PTT / phrase). On end-of-speech,
hand PCM/WAV + session id to a **streaming turn worker**
(`aipc-voice-stream` or `voice-pipecat` stream mode) instead of only
`aipc-voice-once`.

**Why:** Wake + single-mic ownership already works; risk is in the think/speak
path. Alternatives: pure Pipecat graph from boot (higher rewrite cost, weaker
current hardware proof).

### D2 — Orchestrator SSE stream on LiteLLM

**Choice:** Add `POST /chat/stream` (or `POST /chat` with `Accept:
text/event-stream` / `stream: true`) on agent-orchestrator. Implementation
uses LiteLLM streaming completions for the voice system prompt path.
Non-stream `POST /chat` unchanged.

**Why:** Token stream is the largest latency win after end-of-speech. SSE is
simple for a local stdlib/httpx client. Alternatives: websocket (more moving
parts); stream only from LiteLLM bypassing orchestrator (**rejected** — breaks
mem0 / voice prompt / tools later).

### D3 — Sentence/clause TTS queue (not full-reply TTS)

**Choice:** Buffer LLM tokens; on Chinese/English sentence boundary (。！？.!?\n
or length safety cap ~40–80 chars), enqueue TTS for that chunk; player starts
on first ready chunk. Voice system prompt stays short-reply biased.

**Why:** Kokoro already generates internal audio chunks; waiting for full
reply is the main “silent think” gap. Alternatives: wait full text (status
quo); phoneme streaming (not available cleanly in current Kokoro HTTP API).

### D4 — STT: final-first, partial best-effort

**Choice:** S2 **requires** a fast final transcript for the closed utterance
(existing SenseVoice `/transcribe` on the command WAV is OK). Optional
**partial** path: mid-utterance snapshot STT or progressive decode if cheap;
overlay may show partial only when available. Do not block S2 on Paraformer
streaming service.

**Why:** SenseVoice is batch-oriented today; forcing true streaming STT
unblocks nothing if LLM+TTS already stream. Alternatives: mandating Paraformer
streaming (larger module work, can be S2.1).

### D5 — Barge-in via UX + player cancel

**Choice:** Shared state `barge` / energy spike / PTT while `speaking` or
`thinking` cancels: stop paplay/player queue, abort LLM stream client, mark
turn cancelled. Wake remains owner of mic; stream worker does not open a second
arecord during playback barge detect if wake already holds the stream — use
wake energy callback or a lightweight monitor agreed in implementation.

**Why:** Without barge-in, chunked TTS feels worse on long answers. Full duplex
AEC is non-goal.

### D6 — Batch fallback

**Choice:** On stream worker failure (SSE error, TTS chunk fail, timeout),
fall back once to existing `aipc-voice-once --wav` path for that turn and log
`stream_fallback`.

**Why:** Reliability > purity for always-on assistant.

### D7 — Volume policy unchanged

**Choice:** Reuse `voice_audio` hard block on master volume; duck other apps
with short fade; TTS stream normalize to 100% stereo on the TTS sink-input
only.

## Architecture (logical)

```text
                    ┌──────────── wake (phrase/PTT) ────────────┐
                    │  single arecord · adaptive EOS · UX states │
                    └──────────────────┬─────────────────────────┘
                                       │ command PCM/WAV + session
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  stream turn worker                                              │
│   1) STT final (SenseVoice)  ── partial optional ──► UX partial  │
│   2) open SSE /chat/stream   ── tokens ──► sentence buffer       │
│   3) TTS chunk queue         ── wavs ──► player (primary sink)   │
│   4) barge-in cancel ──────────────────────────────────────────  │
└──────────────────────────────────────────────────────────────────┘
          │ LiteLLM only                 │ never set-sink-volume
          ▼                              ▼
   resident-small (voice)         sink-input duck + paplay normalize
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Chinese sentence split cuts mid-thought | Safety max length + prefer 。！？; allow comma only after min chars |
| Many small Kokoro calls add overhead | Coalesce very short chunks; min chars before TTS; parallel next-chunk synth while playing |
| SSE + tools/mem0 complexity | Voice stream path: no tools in S2; mem0 recall pre-stream, remember post-stream |
| Barge false positive from TTS echo | Raise barge energy vs playback; optional mute mic monitor during TTS if needed |
| Stream bugs silent-fail | Explicit fallback to batch once + UX error state |
| Latency budget still bound by first STT | Keep adaptive EOS tight; measure p50/p95 TTFA on hardware |

## Migration Plan

1. Land orchestrator `/chat/stream` + tests (static).
2. Land stream worker behind env `AIPC_VOICE_STREAM=1` (default off until
   hardware-verified).
3. Wake submits to stream worker when enabled; else batch once.
4. Hardware verify: TTFA, barge-in, volume policy, offline.
5. Flip default on after hardware-verified claim (CLAUDE.md §9).
6. Rollback: set `AIPC_VOICE_STREAM=0` or unit drop-in; batch path unchanged.

## Open Questions

1. **Exact SSE event schema** (`token` / `done` / `error` / `session_id`) —
   freeze in tasks before client code.
2. **Whether CosyVoice stays on first Chinese chunk** or Kokoro-only for
   stream path (Cosy cold start may kill TTFA) — recommend Kokoro-first for
   stream; Cosy optional later.
3. **Mic barge source** while wake holds arecord: callback from wake vs
   separate monitor — pick during task 1 design spike (prefer wake signal to
   avoid second capture).
