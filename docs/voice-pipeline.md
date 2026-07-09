# Voice Pipeline

The voice assistant is implemented in staged slices. The current reliable core is a one-shot push-to-talk command; wake word, TTS, and full streaming behavior are layered on top only after their services are verified.

## Stage 1: v0 push-to-talk text-out

```text
Z13 side button or manual command
        │
        ├── direct KDE shortcut capture, if the desktop sees the button
        └── hwdb remap to F20, if discovery only yields MSC_SCAN
                │
                ▼
      KDE shortcut binder / autostart
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
aipc-voice-bind-hotkey --shortcut F20
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

## Hardware handoff

Current status on 2026-07-08: static and render verification passed for the staged v0/PTT, doctor, docs, and opportunistic TTS fallback work. Physical Strix Halo hardware verification was not run in this session.

Run these on the AI PC after deploying the image:

```bash
systemctl is-active aipc-voice-stt-sensevoice.service
aipc-asus-side-button-discover --timeout 20
aipc-voice-bind-hotkey --shortcut F20
aipc-voice-once --seconds 5
aipc doctor
```

Only mark hardware tasks complete after the matching command path is exercised on the physical AI PC. Wake word, listen-off triggers, firstboot voice screens, and full command/chat routing remain pending.
