# Voice wake/latency backlog (→ hermes / next owner)

Filed 2026-07-16 after the wake-deafness fix landed (commit d953a90 + live
phrase_hit mangled-wake patch). Wake now WORKS (嘿助理→STT 我。→phrase_hit).
These remaining items are **beyond voice-loop tuning** and need hermes/owner.

## Status (what's fixed, deployed live, uncommitted-or-committed)

- ✅ Wake deafness: 12s miss-blackout → 1.5s; no threshold escalation on
  playback misses; playback gate 1.4×. (commit d953a90)
- ✅ Follow-up: `_FOLLOWUP_ALWAYS` default ON — short silence-closed window
  after every reply (was 0 opens in 12h). (commit d953a90)
- ✅ Denoise re-enabled (noise floor 13k→~2k); echo-gate off (ECHO_GATE=0)
  to stop the always-True playback misdetection capping threshold at 9000.
- ✅ phrase_hit accepts the STT mangled wake word (嘿→我/咯/咳 + bare 我).
  **This is what made wake actually work.** (live-deployed, uncommitted)
- ✅ Streaming enabled (AIPC_VOICE_STREAM=1) for perceived latency.

Live drop-ins added under `/etc/systemd/system/aipc-voice-wake.service.d/`:
`zzzzz-echo-gate-off.conf`, `zzzzz-stream-on.conf`. Consolidate into repo
defaults once stable.

## Open item 1 — LLM TTFT is the dominant latency (NOT voice-loop)

Symptom: "喚醒後反應好慢，我都說完了".

Evidence (lemonade/podman Telemetry TTFT, 2026-07-15/16):
`TTFT 19.50s`, `48.56s`, `18.46s` when cold/contended; `0.10s`/`2.1s` when warm.
**An 18–48s model load swamps any EOS/voice tuning.** The voice loop is not the
bottleneck.

Likely cause: resident-small model gets evicted/contended (swap admission,
ComfyUI GTT reclamation 0016, other models loaded). Fix belongs in
`modules/llm-lemonade` + `modules/llm-litellm` (residency/idle policy), not voice.
Check: why is the voice `/chat` model cold between turns? `ensure-resident-small`
+ the removed idle-release rewarm may have regressed.

## Open item 2 — SenseVoice STT quality (wake AND commands)

Symptom: wake word 嘿助理 transcribed as `我。`; commands garbled
(`那主汝`, `嘿猪，现在时间现在时间现在时间`).

Evidence (hw A/B 2026-07-16): saying 嘿助理 → STT `我。` **identically on raw
and denoised mic paths** (rms 2284/2429), with `<|yue|>` (Cantonese) language
tag on Mandarin speech. So it's NOT denoise — it's SenseVoice mis-recognition,
likely the wrong-language classification on short isolated phrases.

Fix candidates (STT module, `modules/voice-stt-sensevoice`):
- Force `<|zh|>` instead of auto-detect for the wake + short-command path.
- Evaluate a wake-word-friendlier STT or a dedicated openWakeWord ONNX model
  (`modules/voice-wake` already has openwakeword mode, model slot empty).
- Mic gain is weak (spoken 嘿助理 ~2300 rms, barely above ~2000 ambient) —
  raising `AIPC_WAKE_MIC_VOLUME_PCT` (55) may help SNR.

## Open item 3 — continuous capture / EOS

Symptom: "希望能不用停頓一次講完也能聽到".

Current: capture already runs continuously (one turn hit CMD_MAX_S=14s without
cutting), but ran to MAX → slow hand-off, and long captures STT-garble worse.
`AIPC_WAKE_CMD_END_SILENCE_MS=750`, `CMD_TEXT_STABLE_S=0.9`, `CMD_MAX_S=14`.
Tension: fast EOS (reaction) vs no-cut (continuity). The progressive-STT
text-stable path is meant to resolve it but fires unreliably. Needs
hardware-voice tuning once STT quality (item 2) improves — garbage-in makes
text-stable EOS unreliable.

## Verification tier (CLAUDE.md §9)

- Wake fix: hardware-verified (user confirmed wake works after mangled-wake patch).
- Latency/STT/continuity: diagnosed from live journal + lemonade TTFT telemetry;
  fixes are hermes/backlog scope (LLM residency, STT model), not yet implemented.

## Repro / evidence commands

- Wake STT A/B: capture 4s from `aipc_denoise_out.monitor` vs `alsa_input`,
  POST raw body (Content-Type audio/wav) to `http://127.0.0.1:9001/transcribe`.
- LLM TTFT: `journalctl --since '15 min' | grep -i 'TTFT (s)'` (lemonade telemetry).
- Per-turn voice timing: `aipc voice timings` (was empty — `TurnTimer` may be
  disabled via `AIPC_VOICE_TIMING=0`; re-enable to get perceived/llm_ttft/tts_ttfa).
