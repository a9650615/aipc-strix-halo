# voice-pipecat

Pipecat orchestrator for the voice pipeline. Runs in a Python distrobox container.

## What it does

- Hosts the path-A pipeline: wake → STT-router → LLM (via LiteLLM at `http://127.0.0.1:4000`) → TTS-router.
- Path B (multimodal Qwen2.5-Omni) is a pipeline-config swap, deferred to v2 pending Q1 hardware benchmark.
- Calls `POST /chat` (Phase 4 agent runtime) for LLM replies — text in, text out per D9.
- Ships `aipc-voice-mute.target` (D7): three listen-off triggers (screen-lock, voice mute, GNOME DND) chain into this target.
- Push-to-talk via `Super+Space` (D6).

## Dependencies

- `llm-litellm` — LLM calls route through LiteLLM gateway.
- `voice-wake`, `voice-stt-sensevoice`, `voice-stt-paraformer`, `voice-tts-cosyvoice`, `voice-tts-kokoro`.
- Phase 4 agent runtime (`POST /chat`).

## Spec

- `openspec/changes/phase-3-voice/design.md` — D1, D6, D7, D8, D9.
- Tasks 1.1, 5.1–5.4, 7.1.

## Hardware

- Audio I/O via PipeWire/PulseAudio socket mounted into distrobox.
