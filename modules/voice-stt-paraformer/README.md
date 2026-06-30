# voice-stt-paraformer

Paraformer-zh-streaming STT service for longer audio and dictation.

## What it does

- Runs Paraformer-zh-streaming on iGPU via Lemonade (D4).
- Streaming-capable; router dispatches here for longer utterances.
- Publishes on `127.0.0.1:9002`.

## Dependencies

- `llm-lemonade` — iGPU inference runtime.
- `voice-pipecat` — sends audio segments for transcription.

## Spec

- `openspec/changes/phase-3-voice/design.md` — D4.
- Tasks 1.4, 3.2.

## Hardware

- AMD Strix Halo iGPU (gfx1151) via Lemonade.
