# voice-audio-front

Localhost **audio front gate** for the always-on voice loop.

Short WAV → structured decision (`ignore` | `stt_then_route` | `route`)
**without requiring STT text first**. Fail-soft: if the gate is down or
slow, callers continue with SenseVoice + plan_dispatch.

## Why

False 接话 and energy opens produced junk STT (`我。`) and wasted once
turns. A front gate on the **waveform** can dismiss non-speech before
agent-orchestrator is hit.

## v1 backend

Heuristic (RMS / duration vs noise) — no heavy multimodal weights. Same
JSON schema as a future small audio model (`source=heuristic|model`).

## API

- `GET /healthz` → `{"status":"ok","service":"voice-audio-front"}`
- `POST /gate` body = `audio/wav` → gate JSON

Default bind: `127.0.0.1:9010`.

## Env

| Var | Default | Meaning |
|-----|---------|---------|
| `AIPC_AUDIO_FRONT` | `1` | Enable (clients) |
| `AIPC_AUDIO_FRONT_URL` | `http://127.0.0.1:9010/gate` | Gate endpoint |
| `AIPC_AUDIO_FRONT_TIMEOUT_MS` | `400` | Client hard wall |
| `AIPC_AUDIO_FRONT_SPEECH_RMS` | `3500` | Min RMS for speech |
| `AIPC_AUDIO_FRONT_MIN_S` | `0.35` | Min duration (s) |

## Dependencies

- None on NPU pin for `resident-small` (CPU service).
- Does not unload large Lemonade models.

## Spec

`openspec/changes/voice-audio-front-gate/`
