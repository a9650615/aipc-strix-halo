## Why

Every recent voice/LLM performance fix has been a **manual dodge**, not a
measured decision:

- `7458fb7` NPU-first chat, dirty tools on Vulkan
- `9fbeb51` `aipc models use voice` unloads big LLMs so Cosy ROCm TTS stops
  thrashing agent Vulkan
- `cd346d3` isolate compact/summary traffic onto the NPU coder-compact lane

All three fight the same root cause — **one APU, one iGPU double-booked by
agent LLM (Vulkan) and CosyVoice TTS (ROCm)** — and all three were tuned by
feel (`"felt high"`, `"thrash"`). There is **no per-stage latency number
anywhere** in `docs/voice-pipeline.md` or `docs/agent-log.md`.

This change is **not the performance fix** — the real perceived-latency win is
`voice-streaming-turn` (speak the first sentence before the full reply exists).
That change already requires "first-audio latency MUST be lower than an
equivalent batch turn" and "SHALL document the measured hardware TTFA" — but
**there is no way to measure it today**, so it cannot be verified.

So this change ships the **minimum measurement needed to verify streaming**:
three headline numbers per turn. It is deliberately scoped down — no analytics
backend, no percentile reports — because there is not yet a single turn of data
to analyze. The full telemetry (p50/p95, per-preset breakdown) is **deferred**
until the future GPU-arbiter work actually needs to reason over a fleet of
turns. It is executed **alongside** `voice-streaming-turn`.

## What Changes

- Add a tiny stdlib **turn-timing recorder** to the voice loop that captures
  three headline durations per completed turn and emits **one JSON line per
  turn** to a state file:
  - `perceived` = user-stops → first audible sound (the number users feel)
  - `llm_ttft` = LLM request → first token (streaming path; null on batch)
  - `tts_ttfa` = TTS request → first audio
- Tag each record with a small context label — `path` (`batch`/`stream`),
  `tts_backend`, `preset` — so a streaming turn can be compared against the
  batch baseline it must beat.
- Both `aipc-voice-once` (batch baseline) and the `voice-streaming-turn` worker
  call the same recorder, so the TTFA comparison is apples-to-apples.
- Add a **minimal reader** `aipc voice timings [--last N] [--json]` that dumps
  the most recent turns (raw rows + a simple mean). **No** percentiles, **no**
  `--by preset` grouping — those are explicitly out of scope here.
- Recorder is **best-effort and never in the hot path**: written once at turn
  end, any IO error is swallowed, MUST NOT fail or delay a turn. Disable via
  `AIPC_VOICE_TIMING=0`. Records **exclude transcript and reply text**. The log
  is size-capped (drop oldest) so it cannot grow unbounded.

## Capabilities

### New Capabilities

- `voice-telemetry`: Minimal per-turn latency instrumentation for the voice
  loop — a best-effort recorder of three headline durations plus a small
  context label, a JSON-per-turn record schema (no content text), and a
  raw-tail reader command. Analytics (percentiles, per-scenario breakdown) are
  explicitly deferred to a later change.

### Modified Capabilities

- None. The voice turn path gains timing marks but no behavioural change.
  `voice-streaming-turn` will consume this recorder to satisfy its existing
  (currently unverifiable) TTFA requirement.

## Impact

- **Modules (expected)**: `voice-pipecat` (`aipc-voice-once`, new
  `aipc_voice_timing.py` under `files/usr/lib/aipc-voice/`), `tools/aipc_lib`
  (CLI `aipc voice timings`).
- **APIs**: none external. New on-disk record schema at
  `${XDG_STATE_HOME:-~/.local/state}/aipc-voice/turns.jsonl`.
- **UX**: no runtime UX change; new operator command surfaces the numbers.
- **Hard constraints**: stdlib only (§8); offline; no behavioural change to the
  voice path; logging failure never affects a turn; bootc/ansible parity.
- **Deferred (not in scope)**: p50/p95 and per-preset/backend analytics, a
  metrics daemon or dashboard, and any routing/preset/arbiter behaviour change.
- **Enables**: verification of `voice-streaming-turn`'s TTFA requirement.
