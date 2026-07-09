# voice-tts-kokoro

Local TTS service for spoken assistant replies.

## Current status: espeak-ng backend on :8880 — enabled after hardware verify

The scaffolded `docker.io/aipc/kokoro:latest` image does not exist (same
fictitious-image class as early SenseVoice). This module ships a **native
stdlib HTTP service** (no FastAPI/pydantic — Python 3.14 has no reliable
`pydantic-core` wheel) that exposes an OpenAI-compatible speech endpoint:

```
POST http://127.0.0.1:8880/v1/audio/speech
{"model":"local","voice":"default","input":"...","response_format":"wav"}
→ audio/wav
GET  http://127.0.0.1:8880/healthz
```

Backend is **espeak-ng** (already on the image via `packages.txt`). Chinese
uses `cmn`, English uses `en`. Neural Kokoro/Piper can replace
`synthesize_wav()` later without changing the client (`aipc_voice_tts.py`).

## Dependencies

- `espeak-ng`, `python3-devel` (venv / fastapi)
- `voice-pipecat` — `aipc_voice_tts.speak()` calls this endpoint, then
  falls back to in-process espeak if the service is down

## Spec

- `openspec/changes/phase-3-voice/design.md` — D5 (language-routed TTS;
  this is the minimal local path; CosyVoice cloning remains deferred)

## Verification

- Static: `verify.sh` syntax + unit port
- Hardware: `systemctl start aipc-voice-tts-local` → healthz 200 →
  `aipc-voice-once` speaks the reply (or espeak fallback if service down)
