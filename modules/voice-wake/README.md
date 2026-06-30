# voice-wake

Always-on wake-word detection via openWakeWord, inference on NPU.

## What it does

- Loads a user-trained ONNX model from `/var/lib/aipc/wake/user-model.onnx`.
- Model is trained at firstboot from 3–5 user-recorded samples (D2).
- Runs always-on at ~100 mW (NPU only); STT/LLM/TTS never run idle.
- `BindsTo=!aipc-voice-mute.target` pauses inference on screen-lock / mute / DND (D7).

## Dependencies

- `voice-pipecat` — sends wake events to the pipeline.
- NPU device (`/dev/accel/accel0`).

## Spec

- `openspec/changes/phase-3-voice/design.md` — D2, D7.
- Tasks 1.2, 2.1–2.4, 7.5.

## Hardware

- AMD XDNA 2 NPU (`/dev/accel/accel0`).
