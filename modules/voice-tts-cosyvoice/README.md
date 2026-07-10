# voice-tts-cosyvoice

CosyVoice 3 zero-shot clone TTS for Chinese (primary) — D3 persona sample
+ D5 language-routed TTS.

Ships **`.disabled`** until hardware-verified. Do not remove the gate without
a real CosyVoice round-trip on this host (CLAUDE.md §9).

## What it does

- Native systemd HTTP service on **`127.0.0.1:9880`** (stdlib server — no
  FastAPI dependency in the image path).
- Zero-shot clone from **`/var/lib/aipc-voice/persona/clone.wav`** (firstboot
  / persona wizard sample).
- Model dir: **`/var/lib/aipc-voice/models/cosyvoice3/Fun-CosyVoice3-0.5B-2512`**.
- Runtime install root: **`/var/lib/aipc-voice/cosyvoice/`** (git checkout
  `CosyVoice/` + `venv/`).

## API

```
GET  http://127.0.0.1:9880/healthz
→ {"status":"ok|degraded","backend":"cosyvoice3","clone":true|false, ...}

POST http://127.0.0.1:9880/tts
{"text":"你好，我是你的助手。","prompt_wav":"/var/lib/aipc-voice/persona/clone.wav"}
→ audio/wav   (or JSON 4xx/5xx)
```

`prompt_wav` is optional (defaults to the clone path). Optional
`prompt_text` is the transcript of the prompt wav (CosyVoice zero-shot
input); defaults via `AIPC_CLONE_PROMPT_TEXT`.

When checkout or model weights are missing: `/healthz` → `degraded`,
`/tts` → **503** with a clear message. The unit does not crash-loop.

## Why native systemd, not a quadlet

The previous scaffold pointed at a fictitious CosyVoice container image
that does not exist. Same class of bug as the old sensevoice/orchestrator
scaffolds. There is no real upstream CosyVoice container we pin; the
service is a Python venv + native unit, matching `voice-stt-sensevoice`.

## Build-time vs runtime

| When | What |
|---|---|
| **Image build** (`post-install.sh`) | `mkdir -p` persona / model / install dirs; `systemctl enable aipc-voice-tts-cosyvoice.service`. **No** model download, **no** `systemctl --now`, **no** curl. |
| **Runtime** (manual or first-boot oneshot — not shipped yet) | `git clone` CosyVoice into `/var/lib/aipc-voice/cosyvoice/CosyVoice`, create `venv`, `pip install setuptools` plus the CosyVoice deps, pull `Fun-CosyVoice3-0.5B-2512` into the model dir. Then start/restart the unit. |

Host Python 3.11 is available on this machine for live experiments
(`~/.local/bin/python3.11`); the image path prefers the runtime venv
python, with system `python3` as a degraded fallback so the HTTP shell
stays up before the venv exists.

## Unit / env

`aipc-voice-tts-cosyvoice.service`:

- `AIPC_COSYVOICE_MODEL` — default model dir above
- `AIPC_CLONE_WAV` — default clone sample
- `AIPC_COSYVOICE_DEVICE=cpu` — no GPU assumptions
- `PYTHONPATH` includes CosyVoice checkout + `third_party/Matcha-TTS`

## Dependencies

- Persona sample produced by firstboot / voice wizard (D3).
- `voice-pipecat` will POST `/tts` for Chinese replies (client wiring is
  a separate task; this module only owns the server).

## Spec

- `openspec/changes/phase-3-voice/design.md` — D3, D5
- Tasks 1.5, 4.1

## Hardware

- Target: AMD Strix Halo (gfx1151). Default device is **cpu** until a
  hardware-verified ROCm path is proven; flip
  `AIPC_COSYVOICE_DEVICE` only after that proof.
