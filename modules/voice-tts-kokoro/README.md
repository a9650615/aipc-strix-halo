# voice-tts-kokoro

Kokoro TTS service — English fallback / language-routed.

## What it does

- Runs Kokoro TTS in a container (D5).
- English-language TTS; routed by language tag from STT step.
- Publishes on `127.0.0.1:9012`.

## Dependencies

- `voice-pipecat` — receives text to synthesise.

## Spec

- `openspec/changes/phase-3-voice/design.md` — D5.
- Tasks 1.6, 4.2.

## Hardware

- Runs on CPU; no GPU dependency.
