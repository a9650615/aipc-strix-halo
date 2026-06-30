# voice-stt-sensevoice

SenseVoice-Small STT service for short utterances (<10s).

## What it does

- Runs SenseVoice-Small on iGPU via Lemonade (D4).
- Faster STT for short commands; router dispatches here for <10s audio.
- Publishes on `127.0.0.1:9001`.

## Dependencies

- `llm-lemonade` — iGPU inference runtime.
- `voice-pipecat` — sends audio segments for transcription.

## Spec

- `openspec/changes/phase-3-voice/design.md` — D4.
- Tasks 1.3, 3.1.

## Hardware

- AMD Strix Halo iGPU (gfx1151) via Lemonade.
