# voice-wake

Always-on wake listener that triggers `aipc-voice-once`.

## Current status: **phrase (custom)** default — fast start, low false positive

| Mode | When | Notes |
|---|---|---|
| **`phrase` (default)** | SenseVoice STT healthy | Energy gate → ~1.6s clip → STT → match `/etc/aipc/wake/phrases` |
| `openwakeword` | venv + ONNX models | Pretrained e.g. `hey_jarvis` (English); not free-form Chinese custom |
| `energy` | Last resort | Loudness only — more false triggers |

Edit custom phrases (no model training):

```bash
sudo nano /etc/aipc/wake/phrases   # one phrase per line
sudo systemctl restart aipc-voice-wake
```

Prefer multi-syllable phrases (「嘿助理」) over single short words to cut false hits.

## Single-mic async (no mutual blocking)

One continuous `arecord` stream owns the mic:

| Stage | Who holds mic | What runs |
|---|---|---|
| Listen / wake STT | wake service | energy + short STT phrase check |
| Command after wake/PTT | **same stream** | end-of-speech VAD → WAV |
| LLM / TTS | **background** (`aipc-voice-once --wav`) | no second arecord |

Policy:

- **Recording command + new wake/PTT** → interrupt & restart capture  
- **Busy processing + new command** → barge-in cancel previous once, start new job  
- **Button (控制中心)** → `ptt` on `$XDG_RUNTIME_DIR/aipc-wake.sock` (no second mic)

```bash
echo ptt | nc -U $XDG_RUNTIME_DIR/aipc-wake.sock   # or socat
journalctl -u aipc-voice-wake -f
```

Mute: `aipc-voice-mute.target` + `aipc-voice-mute.service` create
`/run/aipc/voice-mute`; the listener skips while the flag exists.
`Conflicts=aipc-voice-mute.target` also stops the unit when mute is
started. Screen-lock helper: `aipc-voice-mute-screenlock` (session
autostart).

## Suspend / resume (s2idle)

The stack is designed to **allow sleep** and recover after wake:

| Piece | Behavior |
|---|---|
| `system-suspend-gpu-guard` | On AC, blocks sleep only while GPU compute is busy (gfx1151 hang workaround). On battery, never blocks. |
| `/usr/lib/systemd/system-sleep/aipc-ai-stack` | **pre**: stop wake + cancel `aipc-voice-once`/TTS, unduck. **post**: rebuild denoise, restart wake + overlay, nudge STT/mem0/orchestrator. |
| `aipc-voice-wake` | If `arecord` dies mid-run (common after resume), **reconnects mic** up to 15 tries instead of exiting; `Restart=always` as backup. |

Hardware note (this fleet): only `s2idle` is available; deep S3 is not.
Resume-from-s2idle can still hang the GPU if a heavy Vulkan job was in
flight — that is why the GPU guard exists. Voice defaults (`resident-small`
on NPU) are not expected to hold the sleep inhibit.

Manual check after a real sleep:

```bash
systemctl is-active aipc-voice-wake aipc-voice-stt-sensevoice aipc-agent-orchestrator
journalctl -u aipc-voice-wake --since '5 min ago' | grep -E 'reconnect|mic ok|calibrated'
ls $XDG_RUNTIME_DIR/aipc-wake.sock $XDG_RUNTIME_DIR/aipc-overlay.sock
```

## NPU note

Design targets XDNA NPU (~100 mW). openWakeWord on this host uses ONNX
Runtime CPU EP today — same honesty as SenseVoice's CPU default. Flip to
NPU EP when an onnxruntime EP for `/dev/accel/accel0` is validated.

## Spec

- phase-3-voice D2, D7; tasks 1.2, 2.1–2.4, 7.2, 7.5
