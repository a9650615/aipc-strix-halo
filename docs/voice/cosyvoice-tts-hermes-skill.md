---
name: cosyvoice-tts
description: "AIPC CosyVoice3 clone TTS: HTTP API, TW-flat system prompt, speed, instruct2, queue, special tags."
version: 1.0.0
author: birdyo / aipc session
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags:
      - TTS
      - CosyVoice
      - Voice
      - Clone
      - aipc
      - Taiwan-Mandarin
    related_skills: []
---

# CosyVoice3 clone TTS (AIPC)

Local zero-shot / instruct2 TTS for the voice assistant clone persona.

- **URL**: `http://127.0.0.1:9880`
- **Service**: `aipc-voice-tts-cosyvoice.service`
- **Clone wav**: `/var/lib/aipc-voice/persona/clone.wav`
- **Active template**: `/var/lib/aipc-voice/persona/active.json`
- **Code**: `/var/lib/aipc-voice/lib/aipc_tts_cosyvoice/server.py`
  (repo: `modules/voice-tts-cosyvoice/files/usr/lib/aipc-voice/aipc_tts_cosyvoice/server.py`)

Use this when the user asks to **speak / TTS / 念出來 / 用她的聲音** without going through the full voice wake loop. Prefer Cosy over Kokoro for Chinese clone identity.

---

## Health

```bash
curl -sS http://127.0.0.1:9880/healthz | jq .
```

Useful fields:

| field | meaning |
|---|---|
| `status` | `ok` / `degraded` |
| `device` | `cuda` (ROCm) when healthy |
| `mode` | default `zero_shot` |
| `template` | e.g. `self-a` |
| `speed` | default speech rate (env/active) |
| `queue.inflight` | jobs waiting + running |
| `queue.max_inflight` | default **2** (1 run + 1 wait) |
| `queue.gpu_busy` | GPU lock held |
| `queue.busy_rejects` | 503 count |

---

## Basic speak (zero_shot, default clone)

```bash
curl -sS -m 300 -X POST http://127.0.0.1:9880/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，我是你的助手。"}' \
  --output /tmp/cosy.wav && aplay /tmp/cosy.wav
```

CLI shortcut (no instruct/speed knobs):

```bash
aipc-voice-say --cosy "你好，我是你的助手。"
```

---

## Proven system prompt (TW + cute + less retroflex)

Default style on this machine (also in `active.json` / env):

```text
You are a helpful assistant. 请用台湾国语、年轻少女声线（大约二十岁）表达：清亮偏高、轻快可爱、像同龄女生聊天，不要成熟御姐，绝对不要阿姨感或大妈感；尽量不要捲舌音（少用或弱化 zh/ch/sh/r），不要大陆普通话腔调。
```

**Goals**: cuter / slightly higher, less 捲舌, less mainland Putonghua prior.

Per-request override:

```bash
curl -sS -m 300 -X POST http://127.0.0.1:9880/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "……台詞……",
    "mode": "zero_shot",
    "system": "You are a helpful assistant. 请用台湾国语、年轻少女声线（大约二十岁）表达：清亮偏高、轻快可爱、像同龄女生聊天，不要成熟御姐，绝对不要阿姨感或大妈感；尽量不要捲舌音（少用或弱化 zh/ch/sh/r），不要大陆普通话腔调。"
  }' \
  --output /tmp/cosy.wav
```

Even flatter (near flat read):

```text
You are a helpful assistant. 请用台湾国语、几乎平调、像平静念稿，少情绪起伏，不要大陆腔。
```

---

## Speed (faster wall-clock + speech)

Cosy compresses mel when `speed > 1` → faster speech and shorter generate time.

| value | use |
|---|---|
| `1.0` | natural default (model) |
| **`1.2`** | **machine default** — good balance |
| `1.35`–`1.5` | snappier; too high sounds weird |

```bash
curl -sS -m 300 -X POST http://127.0.0.1:9880/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"……","speed":1.35}' \
  --output /tmp/cosy-fast.wav
```

Env (service drop-in): `AIPC_COSYVOICE_SPEED=1.2`
Active template may set `"speed": 1.2`.

---

## instruct2 (emotion / style NL control)

Use when user wants excited / soft / loud / dialect — **not** the flat default.

```bash
curl -sS -m 300 -X POST http://127.0.0.1:9880/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "太好了！！我们做到了！",
    "mode": "instruct2",
    "instruct": "You are a helpful assistant. 请用非常激动、高亢、兴奋的语气大声说，语速偏快，充满能量。<|endofprompt|>"
  }' \
  --output /tmp/cosy-excited.wav
```

Official-style instruct snippets (must end with `<|endofprompt|>`):

- `请非常开心地说一句话。`
- `Please say a sentence as loudly as possible.`
- `请用尽可能快地语速说一句话。`
- `请用台湾国语口音表达，语调平稳偏平……` (flat + TW)

Soft/intimate example:

```text
You are a helpful assistant. 请用非常软、喘息、带欲望的低声娇喘语气说，语速偏慢，气声多一点。<|endofprompt|>
```

Trade-off: strong instruct can **drift identity** off clone; for identity lock prefer zero_shot + system, or swap `clone.wav`.

---

## Special tags (CosyVoice3 tokenizer)

Not separate “pitch faders” — fine-grained tokens:

| tag | effect |
|---|---|
| `<strong>…</strong>` | emphasis / stronger energy |
| `[breath]` / `[quick_breath]` | breath |
| `[sigh]` | sigh |
| `[mn]` | nasal/mn |
| `[laughter]` / `<laughter>…</laughter>` | laugh |
| `[j][ǐ]` style | pinyin **lexical tone** (polyphone), not emotion pitch |

Example:

```text
[breath]啊……[sigh]好湿……把人家<strong>撑得好满</strong>……[mn]嗯啊……
```

Works in `text` for zero_shot / instruct2. Do not over-tag or it can sound broken.

---

## Queue / stability (do not parallel-blast GPU)

ROCm Cosy is **not** safe for concurrent inference.

- Max **2** inflight (1 running + 1 waiting); more → **HTTP 503** `retryable: true`
- Always **serialize** TTS calls; poll `healthz.queue` if needed
- Text length cap: **800** chars (`AIPC_COSYVOICE_MAX_CHARS`)

```bash
# wait until free
while curl -sS http://127.0.0.1:9880/healthz | jq -e '.queue.gpu_busy==true or .queue.inflight>0' >/dev/null; do sleep 1; done
```

Restart if wedged:

```bash
sudo systemctl restart aipc-voice-tts-cosyvoice.service
```

---

## Templates

```bash
aipc-voice-template list
aipc-voice-template current
aipc-voice-template apply self-a
```

Active fields Hermes may care about: `system`, `mode`, `instruct`, `speed`, `clone_wav`.

---

## Performance notes

- Default **fp16 + ROCm** (`venv-rocm`). First load after restart is slow; preload on start.
- Long lines ~ tens of seconds wall (RTF often ~3 on warm model).
- Competing **Vulkan LLM** (Lemonade Qwen / `coder-agentic`) slows Cosy; free GPU if user wants faster TTS.
- MIOpen workspace warnings are noisy but often non-fatal.

---

## JSON contract (POST /tts)

```json
{
  "text": "required string",
  "mode": "zero_shot | instruct2",
  "system": "optional zero_shot system before <|endofprompt|>",
  "instruct": "optional instruct2 control text",
  "speed": 1.2,
  "prompt_wav": "optional path",
  "prompt_text": "optional clone transcript"
}
```

Success → `audio/wav`. Errors → JSON `{ "detail": "..." }` (503 when busy/queue full).

---

## When user says…

| user intent | do |
|---|---|
| 念出來 / TTS / 用她的聲音 | POST `/tts` zero_shot (or `aipc-voice-say --cosy`) |
| 更快 | `"speed": 1.35`–`1.5` |
| 少中國腔 / 台腔 | TW system prompt above |
| 平一點 / 不要情緒 | system: 平稳少起伏 / 像念稿 |
| 興奮 / 高亢 / 嬌喘 | `mode=instruct2` + matching instruct |
| 加重某幾個字 | wrap with `<strong>…</strong>` |
| 卡住 / 炸了 | restart unit; never concurrent /tts |

Do **not** invent other endpoints; stay on `127.0.0.1:9880`.
