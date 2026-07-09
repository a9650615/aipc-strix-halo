# voice-tts-kokoro

**Neural** TTS for the assistant — [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
via [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)
(`ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.4`).

## Chinese support (primary requirement)

Kokoro ships **dedicated Mandarin voice packs** (not espeak phoneme hacks):

| Voice | Style (typical) |
|---|---|
| **`zf_xiaoxiao`** | Default female Mandarin — natural conversational |
| `zf_xiaobei` / `zf_xiaoni` / `zf_xiaoyi` | Alternate female |
| `zm_yunjian` / `zm_yunxi` / `zm_yunxia` / `zm_yunyang` | Male Mandarin |

`aipc_voice_tts.choose_voice()` routes any utterance with ≥12% CJK codepoints
(or ≥2 CJK chars) to `AIPC_TTS_VOICE_ZH` (default **`zf_xiaoxiao`**). English
uses `af_heart`. Override anytime with `AIPC_TTS_VOICE=zf_xiaoxiao`.

Mixed 中英 text is synthesized with the Chinese voice so Mandarin prosody wins
(what you want for this product).

> CosyVoice 2/3 zero-shot cloning remains a follow-up for “sound like me”
> persona work (`voice-tts-cosyvoice`). For **stock high-quality Chinese**,
> Kokoro Mandarin packs are the shipped default.

## API (already what the client calls)

```
GET  http://127.0.0.1:8880/health
GET  http://127.0.0.1:8880/v1/audio/voices
POST http://127.0.0.1:8880/v1/audio/speech
{"model":"kokoro","voice":"zf_xiaoxiao","input":"你好","response_format":"wav"}
→ audio/wav  (24 kHz PCM)
```

## Runtime

Quadlet `aipc-kokoro.container` → systemd. Live ostree hotfix:

```bash
podman run -d --name aipc-kokoro --replace --restart unless-stopped \
  -p 127.0.0.1:8880:8880 \
  ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.4
```

Optional ROCm (experimental upstream): image `…-rocm:latest` + `/dev/kfd` + `/dev/dri`.

espeak-ng stays only as silent-failure fallback inside `aipc_voice_tts.speak()`.

## Hardware-verified (this Strix Halo host, 2026-07-10)

- Image present, container healthy in ~4s
- `zf_xiaoxiao` Chinese sentence → WAV 24 kHz, ~2s wall, `paplay` OK
- `af_heart` English sentence → WAV, play OK
- Mixed 中英 → WAV OK

## Spec

- phase-3-voice D5 (language-routed TTS)
