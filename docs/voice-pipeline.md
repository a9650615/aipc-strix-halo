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

## Stage 2: TTS output (Kokoro-82M neural)

**Backend:** `aipc-kokoro` container — `ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.4`
on **:8880** (OpenAI `/v1/audio/speech`).

**Chinese (default):** voice `zf_xiaoyi` (override `AIPC_TTS_VOICE_ZH`).
Other Mandarin packs: `zf_xiaoxiao`, `zf_xiaobei`, `zf_xiaoni`, `zm_yunjian`, …
(All mainland Mandarin; not Taiwanese accent.)
**English:** `af_heart` (`AIPC_TTS_VOICE_EN`).

`aipc_voice_tts.speak()` routes by CJK density, requests WAV, plays with
`paplay`. espeak-ng is **last-resort only** if Kokoro is down.
`notify-send` still always shows text.

```bash
curl -sS http://127.0.0.1:8880/health
curl -sS http://127.0.0.1:8880/v1/audio/voices | head
# Chinese sample
curl -sS -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"kokoro","voice":"zf_xiaoyi","input":"你好","response_format":"wav"}' \
  -o /tmp/zh.wav && paplay /tmp/zh.wav
aipc-voice-once --seconds 5
```

## Where each stage runs (Strix Halo / Linux)

| Stage | Desired | Reality on this host (2026-07-10) |
|---|---|---|
| Wake (always-on) | **NPU** ~100 mW | Energy VAD on CPU today; openWakeWord→NPU is future |
| STT (SenseVoice) | NPU or iGPU | **CPU** (ROCm `cuda:0` segfaults SenseVoice — known ceiling) |
| LLM (chat) | NPU small + iGPU large | Lemonade **FLM on NPU** (`gemma4-it-e4b-FLM`) + Vulkan iGPU for big models |
| **TTS (Kokoro)** | ideally NPU | **CPU container** — no Linux NPU TTS path yet |

### Why TTS is not on the NPU (yet)

1. **Lemonade `kokoro-v1`** is recipe `kokoro` → **CPU** (official matrix:
   “Text-to-speech | kokoro | cpu”). It is **not** FLM/NPU. Loading it also
   needs the `kokoros` binary from GitHub releases; download can 504.
2. **FLM (XDNA2 NPU on Linux)** serves LLM / ASR / embed / rerank — list has
   `whisper-v3:turbo` and chat models, **no TTS tag**.
3. **AMD Vitis AI ONNX EP** for custom ONNX TTS on Ryzen AI is **Windows-first**;
   Linux x86 NPU offload is incomplete (community: missing `voe` / EP).

So the correct placement today is: **keep NPU free for always-on / small LLM /
future STT**, and run **neural Kokoro TTS on CPU** (already ~1–2 s for a short
sentence; does not fight the LLM for VRAM). When AMD/Lemonade ship NPU TTS on
Linux, swap the backend URL only — client stays OpenAI speech-shaped.

## Stage 3: Wake + mute + hotkey

- **Hotkey**: `aipc-voice-bind-hotkey` (default config `/etc/aipc/voice/hotkey` = `F20`).
  Accepts `qdbus` when `qdbus6` is missing. KDE globalaccel reload is best-effort.
- **Side button**: `aipc-asus-side-button-discover` lists Asus WMI / GZ302 keyboard nodes;
  hwdb template remaps MSC_SCAN → F20.
- **Wake**: `aipc-voice-wake.service` (energy VAD by default; openWakeWord when installed).
  Triggers `aipc-voice-once`. `aipc-voice-mute.target` + flag `/run/aipc/voice-mute`
  pause listening; screen-lock autostart helper starts the mute target.
- **Train**: `aipc-voice-train-wake --samples DIR --label NAME` (v0 marker; ONNX fit later).

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

### Change Kokoro voice without code

```bash
# Chinese (one name per file, # comments ok)
echo zf_xiaoyi | sudo tee /etc/aipc/voice/tts-zh-voice
# English
echo af_heart | sudo tee /etc/aipc/voice/tts-en-voice
# Or one-shot env:
export AIPC_TTS_VOICE_ZH=zf_xiaoni
```

