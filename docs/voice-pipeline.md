# Voice Pipeline

The voice assistant is implemented in staged slices. The current reliable core is a one-shot push-to-talk command; wake word, TTS, and full streaming behavior are layered on top only after their services are verified.

## Stage 1: v0 push-to-talk text-out

```text
push-to-talk or manual command
        │
        ▼
aipc-voice-once
        │
        ├── arecord captures 16 kHz mono WAV
        ├── POST http://127.0.0.1:9001/transcribe
        ├── POST http://127.0.0.1:4100/chat
        └── notify-send text reply, stdout fallback
```

Run manually:

```bash
aipc-voice-once --seconds 5
```

Bind the KDE push-to-talk helper from inside the desktop session:

```bash
aipc-voice-bind-hotkey
```

If KDE global-shortcut tools are missing or no desktop session is active, the helper prints the commands it would run and exits optional.

## Stage 2: TTS output

When TTS services are available, `aipc-voice-once` may speak the assistant reply. Text notification remains the fallback so a TTS failure does not break the assistant.

## Stage 3: Full Phase 3

Full Phase 3 adds wake-word inference, listen-off mute triggers, command-vs-chat routing, firstboot persona/wake screens, and hardware verification on the Strix Halo machine.

## Verification tiers

- Static: script syntax, self-tests, and targeted Python tests pass.
- Render-verified: both bootc and ansible renders produce the expected files.
- Hardware-verified: microphone capture, STT, agent `/chat`, notification or audio output, and desktop hotkey are exercised on the physical AI PC.

Do not treat render-verified as hardware-verified for microphone, TTS, wake word, or desktop hotkey behavior.
