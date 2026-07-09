# voice-wake

Always-on wake listener that triggers `aipc-voice-once`.

## Current status: energy VAD + optional openWakeWord — enabled after hardware verify

Full openWakeWord custom-ONNX training (firstboot 3–5 samples) is staged
as `aipc-voice-train-wake` (v0 writes a marker; real fit is follow-up).
Runtime modes:

| Mode | When |
|---|---|
| `openwakeword` | `openwakeword` importable; pretrained `hey_jarvis` or user ONNX |
| `energy` | Default fallback — RMS threshold on 16 kHz mic frames |

Mute: `aipc-voice-mute.target` + `aipc-voice-mute.service` create
`/run/aipc/voice-mute`; the listener skips while the flag exists.
`Conflicts=aipc-voice-mute.target` also stops the unit when mute is
started. Screen-lock helper: `aipc-voice-mute-screenlock` (session
autostart).

## NPU note

Design targets XDNA NPU (~100 mW). openWakeWord on this host uses ONNX
Runtime CPU EP today — same honesty as SenseVoice's CPU default. Flip to
NPU EP when an onnxruntime EP for `/dev/accel/accel0` is validated.

## Spec

- phase-3-voice D2, D7; tasks 1.2, 2.1–2.4, 7.2, 7.5
