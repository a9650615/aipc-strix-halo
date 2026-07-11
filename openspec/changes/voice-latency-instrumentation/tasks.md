> Status 2026-07-11: groups 1–4 implemented and **render-verified** (ruff clean,
> verify.sh green, 14 new unit tests + render parity/bootc/ansible green, zero
> regressions). Group 5 is **hardware-only** and not run — no AI PC access this
> session.

## 1. Recorder

- [x] 1.1 Define the per-turn JSON record schema (fields: `ts`, headline durations `perceived`/`llm_ttft`/`tts_ttfa`, raw stage marks, labels `path`/`tts_backend`/`preset`, fallback flags); no transcript/reply fields
- [x] 1.2 Add `aipc_voice_timing.py` under `modules/voice-pipecat/files/usr/lib/aipc-voice/`: stdlib `TurnTimer` with `.mark(stage)` (monotonic_ns), `.context(**labels)`, `.flush()` best-effort append + size cap (drop oldest)
- [x] 1.3 `AIPC_VOICE_TIMING=0` disables; `.flush()` swallows all IO errors and never raises; `python aipc_voice_timing.py` self-test prints "self-test OK"
- [x] 1.4 Unit tests: headline-duration derivation, size-cap truncation, no-content-fields assertion, disable flag, flush-never-raises on unwritable path

## 2. Wire Batch Turn

- [x] 2.1 Instrument `aipc-voice-once` with the marks it has today (capture_end, play_start → `perceived`); mic-captured turns only (`--wav`/`--text` handoff paths skipped)
- [x] 2.2 Populate labels from the live turn (`path=batch`; `tts_backend`/`preset` best-effort, left null until a cheap source exists)
- [x] 2.3 Confirm no behavioural change (record emitted with timing on; nothing written with `AIPC_VOICE_TIMING=0`); static path tests added
- [x] 2.4 `verify.sh` self-tests the timing helper import + self-test round-trip

## 3. Minimal Reader

- [x] 3.1 Add `aipc voice timings [--last N] [--json]` in `tools/aipc_lib` reading the JSONL and printing the most recent N rows + a simple mean of the headline durations (no percentiles, no `--by` grouping)
- [x] 3.2 Graceful empty/missing-file and malformed-line handling (skip bad lines, never crash)
- [x] 3.3 Unit tests for tail selection, mean math, and empty/malformed inputs

## 4. Docs And Render

- [x] 4.1 Document the record schema, file location, env flag, and `aipc voice timings` in `docs/voice-pipeline.md`; state it is the enabler for `voice-streaming-turn` TTFA verification and that analytics are deferred
- [x] 4.2 Update `modules/voice-pipecat/README.md` with the helper + no-content/best-effort guarantees
- [x] 4.3 Render-verify: `voice-pipecat` renders into bootc + ansible in sync; module `verify.sh` green

## 5. Baseline Alongside Streaming (AI PC)

- [ ] 5.1 (AI PC) Capture batch `perceived` baseline over N real turns with `aipc-voice-once` (current default preset + TTS backend)
- [ ] 5.2 (AI PC) With `voice-streaming-turn` enabled, capture stream `perceived`/`llm_ttft`/`tts_ttfa` for comparable turns
- [ ] 5.3 (AI PC) Run `aipc voice timings --last N`; confirm stream `perceived` is lower than the batch baseline (satisfies streaming's TTFA requirement) and record the numbers in `docs/voice-pipeline.md` + one `docs/agent-log.md` row
