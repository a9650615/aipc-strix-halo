# Voice Pipeline

## Closed loop (standing product shape)

One always-on loop — not a pile of independent CLIs. Every turn should
complete without leaving the loop:

```text
  mic ──► SenseVoice :9001 ──► local intent? ──yes──► action (e.g. portal open)
                │                      │ no
                │                      ▼
                │              /chat :4100  (resident-small via LiteLLM :4000)
                │                      │
                │                      ├── mem0 recall/remember :7000
                │                      ▼
                └──────────► Kokoro :8880 TTS + notify-send
                                    │
                                    ▼
                              speaker / desktop

  observe / manage:  aipc portal  http://127.0.0.1:7080/
                     aipc voice status|loop|start
                     aipc models use agent|122b|free   (heavy LLMs only)
```

| Piece | Role in the loop |
|---|---|
| **SenseVoice** | hear |
| **resident-small** | think (default `/chat`; NPU) |
| **Kokoro** | speak |
| **mem0** | remember across turns |
| **portal** | see + open by voice (“打开 dashboard”) |
| **agent/122b models** | optional **role layer** — **not** required for the loop |

`AIPC_SUPERVISOR_MODEL` can override `/chat` (e.g. `ornith-35b` after
`aipc models use agent`); the standing default is **resident-small**.
Hermes clients that need tool-calls use LiteLLM **`qwythos-9b`** (role
layer) — never as a substitute for baseline `/chat`.

**Voice path defaults (2026-07-10):**

- `aipc-voice-once` → **direct** `:4100/chat` (not aggregator).  
  Opt-in hub: `AIPC_VOICE_USE_AGGREGATOR=1`.
- Local intents (open dashboard / portal) run **before** chat; STT slurs
  like `dashashboard` still match.
- TTS plays via Kokoro/`paplay` on the **current** default sink — it must
  **not** change system volume.
- No live weather/web in the offline loop (model will say it cannot fetch
  realtime data unless a search/online path is enabled).
- **122B** is optional and memory-heavy; when disabled:  
  `sudo systemctl stop ollama.service && sudo systemctl disable ollama.service`  
  (see `/etc/aipc/models/122b.disabled` and `modules/llm-ollama/README.md`).  
  Re-enable: `sudo systemctl enable --now ollama.service && aipc models use 122b`.  
  Prefer `aipc models use free` so only NPU `resident-small` stays warm.

### How to trigger a turn

| Trigger | How |
|---|---|
| **Keyboard** | **F20** (ASUS side button often remaps here) — bound via `aipc voice bind-hotkey` / `aipc-voice-bind-hotkey --shortcut F20` |
| **KRunner (Spotlight)** | `aipc voice krunner-install` once, then **Alt+Space** (or Meta+Space) and type `aipc 你好` / `助理 问题` / `aipc` for voice/portal actions. Local closed-loop chat + optional TTS; does not change system volume. |
| **Voice (always-on)** | `aipc-voice-wake.service` energy VAD: sustained speech energy → spawns `aipc-voice-once` as the desktop user (TTS/notify work). openWakeWord / custom wake phrase is future when models are installed. |
| **CLI** | `aipc-voice-once --seconds 5` |

Mute always-on listen: activate `aipc-voice-mute.target` (creates `/run/aipc/voice-mute`).

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
                ├── local intent (portal) OR POST :4100/chat
                ├── POST Kokoro :8880 (or Cosy) TTS
                └── notify-send text reply
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

**Chinese (Kokoro pack):** voice `zf_xiaoyi` (override `AIPC_TTS_VOICE_ZH` or
`/etc/aipc/voice/tts-zh-voice`). Other Mandarin packs: `zf_xiaoxiao`,
`zf_xiaobei`, `zf_xiaoni`, `zm_yunjian`, … (mainland Mandarin; not Taiwanese).
**English:** `af_heart` (`AIPC_TTS_VOICE_EN`).

Kokoro is the **neural fallback** for Chinese when CosyVoice is unavailable,
and the primary path for English. espeak-ng is **last-resort only**.
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

## Stage 2b: CosyVoice clone TTS (preferred Chinese)

**Backend:** `aipc-voice-tts-cosyvoice` on **127.0.0.1:9880**
(`GET /healthz`, `POST /tts`). CosyVoice 2 zero-shot cloning is the preferred
Chinese TTS when the service and model are present.

**Clone sample path:** `/var/lib/aipc-voice/persona/clone.wav`

**How the sample was produced (this host):** extract a short clean speech
segment from a personal video (ffmpeg audio demux), then apply mild denoise
and normalize before writing the mono WAV reference used for zero-shot clone.
Longer / noisier clips degrade clone quality — aim for ~5–10 s of clear speech
with little background music.

**Persona config:** `/etc/aipc/voice/persona.yaml` (module ships a skeleton;
`name` is filled at firstboot). Fields:

| Key | Meaning |
|---|---|
| `name` | Assistant name (empty until firstboot) |
| `clone_wav` | Reference WAV for CosyVoice zero-shot |
| `tts_prefer` | `cosyvoice` or `kokoro` |
| `kokoro_voice_zh` | Kokoro Mandarin pack when falling back |

**TTS fallback chain (Chinese / CJK-dense replies):**

```text
CosyVoice :9880/tts  (clone.wav reference)
        │ fail / degraded / not installed
        ▼
Kokoro :8880/v1/audio/speech  (voice zf_xiaoyi)
        │ fail
        ▼
espeak-ng  (last resort)
```

English replies stay on Kokoro → espeak (CosyVoice skipped unless forced).

```bash
# CosyVoice health + clone synth (when service is up)
curl -sS http://127.0.0.1:9880/healthz
curl -sS -X POST http://127.0.0.1:9880/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，我是你的语音助手"}' \
  -o /tmp/cosy.wav && paplay /tmp/cosy.wav
# Confirm clone sample exists
ls -l /var/lib/aipc-voice/persona/clone.wav
cat /etc/aipc/voice/persona.yaml
```

The CosyVoice module may still ship `.disabled` until hardware-verified; until
then the client falls through to Kokoro automatically.

## Online assistant mode (aggregator + multi-site web engine)

Phase/change: OpenSpec `assistant-chatgpt-online`.

**Not the default for push-to-talk.** `aipc-voice-once` uses direct `/chat`
unless `AIPC_VOICE_USE_AGGREGATOR=1`. Text entry still uses `aipc-assistant`.

```text
aipc-assistant  (or aipc-voice-once with AIPC_VOICE_USE_AGGREGATOR=1)
        │
        ▼
  assistant-aggregator (NPU-first: resident-small control + local chat)
        │
        ├─ mode=local  → LiteLLM resident-small (auto → :4100 fallback)
        └─ mode=online → assistant-chatgpt WebEngine (headless by default)
                              site pack: chatgpt.com (more sites via sites.yaml)
```

| Command | Purpose |
|---|---|
| `aipc-assistant` | Unified text entry + setup checklist |
| `aipc-assistant setup [--online]` | First-run; online login is **headed** only here |
| `aipc-assistant mode local\|online` | Switch backend |
| `aipc-chatgpt auth login` | Manual login (headed); exports session only |
| `aipc-chatgpt inject --send` | Headless inject (no desktop window) |
| `aipc-chatgpt sites list\|plan` | Multi-site config + NPU setup plan |

**Keywords (user transcript / turn text):** 結束語音 → `session_close`; 回到本地 → mode local; 網上助理 → mode online. Controller uses `resident-small` JSON with keyword priority for lifecycle actions.

**Degraded:** DOM/transcript scrape may fail → keyword automation limited; local path still works. Online never uses OpenAI platform API for this surface (subscription client only).

**Headless policy:** automation defaults headless (`sites.yaml engine.headless: true`). Only interactive login uses a visible window (`AIPC_WEB_HEADED=1` or `auth login`).

**Non-goals:** Realtime API billing, scraping as stable OpenAI-compatible API, silent desktop-audio capture.

## Always-on baseline (not torn down by model presets)


Standing decision (2026-07-10): these stay resident unless a better combo
is hardware-proven and explicitly adopted:

| Piece | Role |
|---|---|
| **resident-small** | NPU/FLM small LLM (via Lemonade) |
| **SenseVoice** | STT (`aipc-voice-stt-sensevoice`, :9001) |
| **Kokoro** | Neural TTS (`aipc-kokoro`, :8880) until CosyVoice clone is ready |
| **mem0** | Local memory (`aipc-mem0`) |

`aipc models use agent|122b|free` only switches **heavy role LLMs**. It must
not stop SenseVoice / Kokoro / mem0. 122B vs agent Vulkan is exclusive at
the **role** layer only; baseline coexists with either.

## Role layer (optional; on top of baseline)

Standing decision (2026-07-10, trial closed — Hermes OK on this host).
These are **not** always-on and **must not** replace the closed-loop table
above. Consumers go through LiteLLM aliases (CLAUDE.md §7).

| Alias | Role | Notes |
|---|---|---|
| **`qwythos-9b`** | Hermes / agent **decision + tool-call** brain | Lemonade Vulkan ~5.6GB; `aipc models use agent` warm default; co-resides with one other Vulkan LLM under `max_loaded_models=2` |
| `coder-agentic` | Heavier tool-call / coding | Optional peer in agent role |
| `assistant-gemma` | Agent-role chat responder | Complementary to Qwythos, not voice default |
| `ornith-35b` | Reasoning / agentic coding | On demand |
| `qwen35-122b-q3` | Giant coding (Ollama) | Exclusive with agent Vulkan; unload via `agent`/`free` |

Hard constraints from system architecture:

1. **Baseline stays up** when agent/122b/free switches — NPU `resident-small`
   + STT/TTS/mem0/portal are never torn down by presets.
2. **Voice `/chat` default remains `resident-small`** — Qwythos is not the
   closed-loop think piece.
3. **Hermes (and similar agent CLIs) → `qwythos-9b` via LiteLLM** when the
   agent role is active; do not hardcode Lemonade/Ollama URLs.
4. **UMA budget** — agent Vulkan stack vs 122B is exclusive; Qwythos is small
   enough to share a slot with one peer, not an excuse to keep 122B loaded.

## aipc CLI — install vs day-to-day management

**Install / image ship path** (durable, both targets):

| Piece | Module | Notes |
|---|---|---|
| STT SenseVoice | `modules/voice-stt-sensevoice` | systemd unit `:9001` |
| TTS Kokoro | `modules/voice-tts-kokoro` | quadlet `aipc-kokoro` `:8880` |
| Push-to-talk + helpers | `modules/voice-pipecat` | `aipc-voice-once`, hotkey, status script |
| mem0 | `modules/memory-mem0` | `:7000` |
| resident-small | `modules/llm-lemonade` + `llm-models` | NPU FLM alias |

Modules land via `aipc render bootc` / `aipc render ansible` then image
switch or playbook — not by hand-copying under `/var/lib` alone. Live
hotfixes are for bring-up only; durable state stays in `modules/`.

**Runtime control plane** (always prefer these over raw systemctl/podman):

```bash
aipc voice status          # closed-loop probe (hear→think→speak→remember→UI)
aipc voice loop            # alias for status
aipc voice start           # start full closed-loop units
aipc voice stop --yes      # STT/TTS only; mem0 + resident-small stay
aipc voice once --seconds 5
aipc voice bind-hotkey
aipc voice record-clone

aipc portal                # localhost entry page URL + service card summary
aipc portal open           # open http://127.0.0.1:7080/ (auto-start if needed)
aipc portal serve          # foreground server if aipc-portal.service not installed yet

aipc doctor                # module verify.sh + voice static checks
aipc models use agent|122b|free   # heavy LLMs only; never tears baseline
aipc mem0 migrate-from-saas       # optional SaaS import
aipc config --mem0-local          # point Claude plugin at local mem0
```

Shipped `aipc-voice-*` binaries remain for shortcuts and desktop launchers;
`aipc voice …` is the supported operator surface. For a browser overview of
baseline + peers without retyping status commands, use `aipc portal open`
(module `system-aipc-portal`; pre-bootc hosts: `aipc portal serve` then open).

### Voice → open dashboard

After push-to-talk / wake, say any of:

- 「打开 dashboard」「打開面板」「打开管理介面」
- “open portal” / “open dashboard” / “show dashboard”

`aipc-voice-once` matches these **locally** (before `/chat`), then runs
`aipc portal open` which auto-starts the portal if needed and opens
`http://127.0.0.1:7080/`. Best from the desktop hotkey session; system wake
best-efforts `runuser` + `DISPLAY=:0`.

## Where each stage runs (Strix Halo / Linux)

| Stage | Desired | Reality on this host (2026-07-10) |
|---|---|---|
| Wake (always-on) | **NPU** ~100 mW | Energy VAD on CPU today; openWakeWord→NPU is future |
| STT (SenseVoice) | NPU or iGPU | **CPU** (ROCm `cuda:0` segfaults SenseVoice — known ceiling) |
| LLM (chat) | NPU small + iGPU large | Lemonade **FLM on NPU** (`gemma4-it-e4b-FLM`) + Vulkan iGPU for big models |
| **TTS (CosyVoice clone)** | ideally NPU | **CPU** on :9880 — no Linux NPU TTS path yet |
| **TTS (Kokoro fallback)** | ideally NPU | **CPU container** on :8880 — same NPU gap |

### Why TTS is not on the NPU (yet)

1. **Lemonade `kokoro-v1`** is recipe `kokoro` → **CPU** (official matrix:
   “Text-to-speech | kokoro | cpu”). It is **not** FLM/NPU. Loading it also
   needs the `kokoros` binary from GitHub releases; download can 504.
2. **FLM (XDNA2 NPU on Linux)** serves LLM / ASR / embed / rerank — list has
   `whisper-v3:turbo` and chat models, **no TTS tag**.
3. **AMD Vitis AI ONNX EP** for custom ONNX TTS on Ryzen AI is **Windows-first**;
   Linux x86 NPU offload is incomplete (community: missing `voe` / EP).
4. **CosyVoice 2** runs as a native Python service on **CPU** for the same
   reason — there is no shipped NPU backend for clone TTS on Linux yet.

So the correct placement today is: **keep NPU free for always-on / small LLM /
future STT**, and run **CosyVoice (preferred zh clone) + Kokoro (fallback / en)
on CPU**. Neither TTS path uses the NPU. When AMD/Lemonade ship NPU TTS on
Linux, swap the backend URL only — client stays speech-shaped.

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

