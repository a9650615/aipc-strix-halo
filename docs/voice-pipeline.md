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

**2026-07-09 live status (this Strix Halo host):**

| Piece | State |
|---|---|
| `aipc-agent-orchestrator` `/chat` | Running; hardware round-trip OK (≈90s wall for short reply under load) |
| LiteLLM + Lemonade | Running |
| `aipc-mem0` | Running |
| `aipc-voice-stt-sensevoice` | Live unit under `/var/lib/aipc-voice` (ostree `/usr` RO). Fixed SELinux `bin_t` on `venv/bin` after 203/EXEC crash-loop. First start may download ~936 MB `model.pt` into `MODELSCOPE_CACHE`. |
| Mic default source | Must be real `alsa_input…`, not `…monitor` |
| Wake / TTS / full Pipecat | Still deferred (Stage 3) |

Run these on the AI PC:

```bash
systemctl is-active aipc-voice-stt-sensevoice.service
curl -sS http://127.0.0.1:9001/healthz
aipc-asus-side-button-discover --timeout 20
aipc-voice-bind-hotkey --shortcut F20
aipc-voice-once --seconds 5
aipc doctor
```

If SenseVoice dies with `203/EXEC`, relabel and restart:

```bash
sudo chcon -R -t bin_t /var/lib/aipc-voice/venv/bin   # live-hotfix path
# or, after a real image deploy:
sudo restorecon -R /usr/lib/aipc-voice/venv/bin
sudo systemctl restart aipc-voice-stt-sensevoice.service
```

Only mark OpenSpec hardware tasks complete after the matching command path is exercised. Wake word, listen-off triggers, firstboot voice screens, and full command/chat routing remain pending.
