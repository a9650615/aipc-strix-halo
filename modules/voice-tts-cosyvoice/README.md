# voice-tts-cosyvoice

CosyVoice 2 TTS service — zh primary, voice cloning support.

## What it does

- Runs CosyVoice 2 on iGPU via Lemonade (D5).
- Uses firstboot persona record for voice preset or zero-shot cloned sample (D3).
- User-cloned voice samples stored in `/etc/aipc/cosyvoice/voices/`.
- Primary TTS for Chinese; routed by language tag from STT step.

## Dependencies

- `llm-lemonade` — iGPU inference runtime.
- `voice-pipecat` — receives text to synthesise.

## Spec

- `openspec/changes/phase-3-voice/design.md` — D3, D5.
- Tasks 1.5, 4.1.

## Hardware

- AMD Strix Halo iGPU (gfx1151) via Lemonade.
