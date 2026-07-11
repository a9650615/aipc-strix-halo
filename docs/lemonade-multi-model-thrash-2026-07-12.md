# Lemonade multi-model thrash (2026-07-12)

Status: **recorded, not fixed**. Mitigated temporarily by stopping fan-out services and restarting the LLM stack. Revisit later.

Hardware-verified diagnosis on the live Strix Halo box (Bazzite / aipc). Write-up only — no permanent config change landed from this incident.

---

## Symptom

- Hermes (or other clients) appears stuck; GPU% low (~10–30%) while VRAM high (~97%).
- Lemonade `:8001` health endpoints time out; LiteLLM still answers `/health/liveliness`.
- Journal spam: `Auto-loading model: …` → `Slot limit reached` → `Evicting` → `Another load is in progress, waiting…`.
- LiteLLM holds a large pile of ESTABLISHED sockets to `:8001` (observed ~100–120).
- Equal auto-load counts across many models (not a single long decode).

## Root cause (short)

Several AIPC consumers fan out to **7+ local model aliases at once**, but Lemonade is configured with **`max_loaded_models: 4`**. Router LRU-evicts continuously; the HTTP gateway stops responding; clients hang/retry and make it worse.

Not primarily “GPU too weak” — mostly **model load thrash + connection backlog**, not steady token decode.

---

## Model aliases involved

| LiteLLM alias | Backend (Lemonade) | Typical callers |
|---|---|---|
| `coder-agentic` | Qwen3.6-35B Aggressive Q4_K_P | Hermes default |
| `ornith-35b` | Ornith-1.0-35B Q4_K_M | aipc-agent daily/tools, skill learn, MOA aggregator |
| `qwythos-9b` | Qwythos-9B | intent classifier (`AIPC_CLASSIFIER_MODEL`) |
| `assistant-gemma` | Gemma4-26B Uncensored Balanced | voice /chat default, skill-learn fallback |
| `coder-compact` | Gemma4-E2B | Hermes auxiliary (compression, web_extract, session_search) |
| `vlm-screen` | Qwen2.5-VL-7B | `screen_see` |
| `vlm-qwen2vl` | Gemma4-26B Vision | browser / agent vision |
| `resident-small` | gemma4-it-e4b-FLM (NPU/FLM) | voice short turns, titles; `aipc-resident-small` pin |

Live constraint (at incident):

```text
/var/lib/aipc-lemonade/cache/config.json → max_loaded_models: 4
```

(`configure-lemonade.sh` currently sets 4; older notes mention 8 as desirable for dual 35B + compact.)

---

## Services that caused / amplified the problem

### Primary fan-out (stop these first when thrashing)

| Unit | Role |
|---|---|
| `aipc-agent-orchestrator.service` | Multi-model agent graph (`:4100`) |
| `aipc-voice-wake.service` | Wake → routes into agent |
| `aipc-voice-stt-sensevoice.service` | STT path into voice stack |
| `aipc-voice-audio-front.service` | Audio front gate |
| `aipc-command-center.service` | Hardware key → voice |
| `aipc-voice-overlay.service` (user) | Overlay UI into voice |

Together: **any voice activity can request classifier + chat/tool model + VLM + learn path** while Hermes also holds `coder-agentic`.

### Amplifiers (turn hang into wedged gateway)

| Unit | Role |
|---|---|
| `lemonade.service` | Inference server; slot=4 + multi-load = thrash; health dies |
| `litellm.service` | Proxy; accumulates huge backend connection backlog; retries |

### Secondary / competing

| Unit / process | Role |
|---|---|
| `aipc-portal.service` | Control Center; dashboard probes; was ESTAB to LiteLLM during incident |
| `aipc-resident-small.service` | Pins resident-small; can fight for slots on lemonade restart (`activating`) |
| Hermes WebUI (`~/.hermes/hermes-webui/ctl.sh`) | Long `coder-agentic` stream (~71k ctx) hung; retries after 500s — not root cause but held the visible “stuck” session |

`aipc-lemonade-idle-release.timer` (every 1m) **could not help** during the incident: it logged `Lemonade health unreachable`.

---

## Evidence chain (incident path)

```text
Hermes / voice / agent / portal
        │
        ▼
   LiteLLM :4000          (liveliness OK; many backend conns)
        │
        ▼
   Lemonade :8001         (health timeout; ~200 ESTAB at peak)
        │
        ▼
   llama-server × N       (serial load/evict of 26B/35B/VL/…)
```

Timeline snapshot (local morning 2026-07-12):

1. Hermes session `20260711_212040_36e579` on `coder-agentic` testing ComfyUI.
2. API call #3 streaming from ~06:09; no completion for >13 minutes.
3. Concurrent auto-loads of Ornith / Gemma26B / VL / Qwythos / E2B / Qwen3.6.
4. GPU decode not saturated; VRAM thrash.

---

## Temporary mitigation applied (live, reversible)

**Stopped (left inactive):**

```bash
# system
aipc-agent-orchestrator
aipc-voice-wake
aipc-voice-stt-sensevoice
aipc-voice-audio-front
aipc-command-center
aipc-portal

# user
aipc-voice-overlay
```

**Restarted:**

```bash
sudo systemctl restart lemonade.service
sudo systemctl restart litellm.service
# Hermes WebUI (cleared hung turn)
~/.hermes/hermes-webui/ctl.sh restart
```

**Post-mitigation check (good state):**

- Lemonade `/api/v1/health` → `status: ok`, `all_models_loaded: []`
- No Auto-loading/Evict spam for 20s
- `:8001` ESTAB ~1
- VRAM ~7%
- Hermes WebUI healthy, 0 active streams

**Restore voice/agent later (only after Hermes work finishes if still busy):**

```bash
sudo systemctl start \
  aipc-agent-orchestrator \
  aipc-voice-wake \
  aipc-voice-stt-sensevoice \
  aipc-voice-audio-front \
  aipc-command-center \
  aipc-portal
systemctl --user start aipc-voice-overlay
```

---

## Fix directions (for later — not done)

1. **Concurrency policy**: only 1–2 “heavy” models warm at a time; pin `coder-agentic` when Hermes is primary.
2. **Raise / retune `max_loaded_models`** only if VRAM math allows (docs historically wanted 8; live was 4). Prefer explicit pins over “load everything”.
3. **Voice path**: classifier + tool + VLM must not all cold-load 35B-class weights on every utterance; default voice to `resident-small` / compact and escalate.
4. **LiteLLM**: avoid full `/health` model completion probes if any dashboard uses them; lower backend connection pile-up / retries under load.
5. **Portal**: health probes must be cheap (liveliness only), never force-load every alias.
6. **Hermes**: large-context agentic sessions should not share the machine with voice multi-model fan-out; optional: pause voice services while long agent turns run.
7. **idle-release**: only useful when health works; thrash makes it a no-op — fix thrash first.

---

## Related paths

- `modules/llm-lemonade/files/usr/lib/aipc/llm-lemonade/configure-lemonade.sh` (`max_loaded_models`)
- `modules/llm-lemonade/README.md` (slot / thrash history)
- `/etc/aipc/litellm/config.yaml` (alias → Lemonade mapping)
- `~/.hermes/config.yaml` (default `coder-agentic`, auxiliary → `coder-compact`)
- `/var/lib/aipc-agent/aipc_agent/` (classifier `qwythos-9b`, daily `ornith-35b`, screen `vlm-screen`)

---

## One-liner

**Voice + agent-orchestrator fan out to 7 models; Lemonade only holds 4 → thrash; LiteLLM connection backlog freezes the gateway; stop fan-out + restart lemonade/litellm to recover.**
