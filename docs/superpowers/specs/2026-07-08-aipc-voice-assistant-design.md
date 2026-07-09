# AIPC Voice Assistant Completion Design

Date: 2026-07-08
Approved approach: staged completion, starting with the smallest daily-usable slice and then layering speech output and full Phase 3 features.

## Context

`phase-3-voice` already exists. The repo currently has a reduced v0 voice path: `aipc-voice-once` records audio, posts it to the SenseVoice STT service, sends text to the agent `/chat` endpoint, and displays the answer through desktop notification text. This is useful plumbing, but it is not yet a daily assistant because invocation, checks, documentation, and speech output are incomplete.

## Goals

1. Make the v0 assistant daily-usable with a push-to-talk entry point.
2. Add voice health checks and documentation so failures are visible.
3. Add TTS output after v0 is stable, with text notification fallback.
4. Finish full Phase 3 behavior only after the smaller layers are render-verified.
5. Keep local/offline and LiteLLM gateway constraints intact.

## Non-goals

- Do not make wake-word or TTS model downloads happen at image build time.
- Do not claim wake-word, TTS, or end-to-end speech is hardware-verified until it is tested on the physical Strix Halo machine.
- Do not bypass LiteLLM for LLM calls from voice modules.
- Do not hardcode the primary username into installed module files.

## Architecture

The completion is staged:

```text
Stage 1: Daily-usable v0

push-to-talk hotkey
        │
        ▼
aipc-voice-once
        │
        ├── record mic audio
        ├── POST /transcribe to local STT
        ├── POST /chat to agent-orchestrator
        └── notify-send text reply

Stage 2: Speech output

agent reply
        │
        ▼
TTS router
   ├── zh/ja/ko or configured Chinese voice -> CosyVoice
   ├── en and light fallback -> Kokoro/Piper
   └── service/model unavailable -> notify-send text reply

Stage 3: Full Phase 3

wake word / force wake
        │
        ▼
STT router -> command/chat router -> agent / daily assistant -> TTS router
        ▲
        │
listen-off triggers: lock screen, DND, explicit mute
```

## Stage 1: Daily-usable v0

Stage 1 keeps the current reduced v0 scope and makes it easy to invoke and diagnose.

### Push-to-talk

Add an installed helper that configures the desktop hotkey to run `aipc-voice-once`. The helper must be idempotent and must resolve the active desktop user dynamically at runtime. If desktop keybinding automation is unavailable, it should print a one-line manual command instead of failing the module build.

The shipped default target is `Super+Space` only if it does not override an existing binding. If the binding exists, the helper must leave it alone and report the conflict.

### Doctor checks

Add voice checks to `aipc doctor` for:

- `aipc-voice-once` exists and is executable.
- SenseVoice STT systemd unit is installed.
- agent `/chat` endpoint is configured/reachable when the service is running.
- desktop notifier exists, or text output fallback is reported as unavailable.
- optional checks for hotkey registration and microphone access.

Checks that require a running desktop session or microphone should be `INFO`/`OPTIONAL`, not hard failures during render-only verification.

### Documentation

Add `docs/voice-pipeline.md` with the staged pipeline, the current v0 status, how to invoke the assistant, how to bind the hotkey manually if needed, and the verification tier reached.

## Stage 2: TTS output

Add the minimum TTS path that turns an agent text reply into audio when a local TTS service is available.

- Keep `notify-send` as fallback.
- Route Chinese/default local persona speech to CosyVoice.
- Route English/lightweight speech to Kokoro/Piper.
- Do not block the v0 text path on TTS readiness.
- TTS services must be runtime services, not build-time probes.

## Stage 3: Full Phase 3

Finish the larger OpenSpec tasks only after Stage 1 and Stage 2 are stable:

- wake-word service and training artifacts
- NPU/runtime inference path where available
- listen-off triggers via `aipc-voice-mute.target`
- command-vs-chat router
- firstboot persona and wake-word screens
- full end-to-end hardware verification

This stage may need separate dispatch because it touches desktop integration, model runtime, and hardware verification.

## Error handling

- If STT fails, show a short desktop notification and exit non-zero.
- If `/chat` fails, show the error summary and exit non-zero.
- If TTS fails, fall back to text notification and return success if the assistant answer was produced.
- If hotkey registration conflicts, leave existing user settings untouched and report the manual command.
- Build-time scripts must not start services, probe health endpoints, or require GPU/NPU/microphone access.

## Testing and verification

Stage 1 verification:

- Static: targeted Python/shell syntax checks for touched scripts.
- Static: targeted unit tests for doctor/check helpers where existing test patterns exist.
- Render-verified: `tools/aipc render bootc` and `tools/aipc render ansible --check`.
- Hardware-verified: manual `aipc-voice-once` and hotkey invocation on the Strix Halo machine.

Stage 2 verification:

- Static/render checks as above.
- Runtime service checks for TTS endpoints.
- Hardware-verified speech playback before claiming spoken output complete.

Stage 3 verification:

- Full Phase 3 OpenSpec validation.
- Wake-word, lock/DND mute, PTT, command routing, chat routing, and TTS exercised on hardware.

## OpenSpec updates

Use the existing `openspec/changes/phase-3-voice` change. Mark tasks done only when the matching implementation and verification tier are real. Reduced v0 tasks should remain explicitly partial until the full Phase 3 requirement is satisfied.

## Deliberate simplifications

- Start with a hotkey-triggered one-shot command instead of streaming Pipecat. Add streaming only when wake word, barge-in, and TTS are actually being built.
- Keep text notification fallback forever; it is the cheap debug path and prevents TTS failures from breaking the assistant.
- Keep firstboot UI out of Stage 1 unless an existing firstboot contribution pattern is already present and cheap to reuse.
