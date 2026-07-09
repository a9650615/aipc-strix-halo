## Context

Phase 3 voice is a local cascaded pipeline (`aipc-voice-once`: STT →
`POST :4100/chat` → TTS). Phase 3 design non-goals include cloud STT/TTS
fallback for that path. The user also holds a ChatGPT **subscription** and
wants GPT-Live-class Voice naturalness **without** platform API billing.

This change adds an **explicit online assistant mode** that drives the
official web client (`chatgpt.com`) inside an **aipc-owned Chromium
wrapper** (bundled engine + persistent profile + loopback automation),
not the user's daily Chrome/Flatpak browser. Local mode remains default.

Stakeholders: desktop user on Bazzite/KDE (this host), voice entrypoints,
optional agent context packing, privacy-conscious local-first defaults.

## Prime premise: mutual integration

**All goals in this change share one non-negotiable premise: they must
integrate with each other and with the rest of aipc—not ship as isolated
toys.**

Feature packs, controller, Voice, inject, system audio, handoff, Projects,
and future web-only surfaces are **one product surface** with shared state:

```text
  ┌──────────────────────────────────────────────────────────┐
  │  unified entry: aipc-assistant (text | voice adapters) │
  │    → TurnRequest { modality, text?, session_id, … }      │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │  AGGREGATOR (modular hub — single orchestration brain)   │
  │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐ │
  │  │ mode    │ │ context  │ │ control │ │ action bus   │ │
  │  │ local/  │ │ mem0 /   │ │ small   │ │ allow-listed │ │
  │  │ online  │ │ persona/ │ │ model + │ │ executor     │ │
  │  │         │ │ :4100…   │ │ keywords│ │              │ │
  │  └─────────┘ └──────────┘ └─────────┘ └──────────────┘ │
  │  ┌────────────────────────────────────────────────────┐  │
  │  │  backends (pluggable modules, not hard-wired UX)   │  │
  │  │  local-chat │ online-web │ tts │ stt │ packs…     │  │
  │  └────────────────────────────────────────────────────┘  │
  │  status / events / degrade flags                        │
  └────────────────────────────┬─────────────────────────────┘
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   local backend         online backend        optional packs
   :4100 /chat           engine+session        project/gpt/…
   (+ TTS if voice)      inject ± voice        system_audio…
```

### The aggregator (super hub)

**Role:** the **only** place that decides *how a turn is fulfilled* and
*which modules run*. Entry points are thin; backends are dumb-ish
executors; packs register capabilities. Nothing important talks
sideways without going through the aggregator.

**Modular slots** (each is a plugin interface, enable/disable via config):

| Slot | Responsibility | Examples on this host |
|---|---|---|
| `entry.*` | Normalize input → `TurnRequest` | text CLI, voice-once, later wake |
| `control.*` | Intent / action selection | controller (`resident-small`), keywords |
| `context.*` | Build inject/local system context | persona, mem0, later `:4100/context` |
| `backend.local` | Local assistant completion | agent-orchestrator `:4100` |
| `backend.online` | Subscription web surface | assistant-chatgpt packs (engine…) |
| `output.*` | Present result | notify, TTS, scrape text, stdout |
| `pack.*` | Optional features | handoff, system_audio, project, … |
| `status` | Aggregate health | doctor / `aipc-assistant status` |

**Pipeline (every turn):**

```text
1. entry → TurnRequest
2. aggregator.load mode + session
3. context.assemble (soft-fail each source)
4. control.decide (model then keywords) → Action[]
5. execute actions (may change mode, open online, close window…)
6. route remaining user text to backend.local | backend.online
7. output.present
8. emit events (transcript, actions) for packs/hooks
```

**Rules for modules hanging on the aggregator:**

1. **Register, don't bypass** — backends/packs expose a small API; no
   private second browser or second mode file.
2. **Composable** — e.g. handoff action + online backend + inject context
   + system_audio pack can all fire in one turn if control requests it.
3. **Order is explicit** — action bus has priority/phases (mode change →
   session open → inject → voice → close); packs declare phase.
4. **Shared event bus** — transcript, action results, errors; packs
   subscribe via hooks.
5. **Degrade per slot** — missing online backend does not kill local;
   controller down → keywords; mem0 down → thinner context.
6. **One status document** — aggregator merges slot health.

A feature that cannot attach as a slot/pack on the aggregator is **out of
scope** until redesigned.

**Integration rules (apply to every pack and task):**

1. **One aggregator** — sole orchestrator between entry and backends.
2. **One session bus** — packs share engine/session when online.
3. **One mode of truth** — `local` | `online`.
4. **One unified entry** — text and voice → `TurnRequest` only.
5. **One control plane** — control slot → allow-listed actions only.
6. **Bidirectional handoff** — via actions on the aggregator, not ad-hoc.
7. **aipc context via context slot** — persona/mem0/`:4100` soft-fail.
8. **LiteLLM for local NLU** — controller uses gateway aliases only.

## Goals / Non-Goals

**Goals:**

- **Integrated online surface** under the prime premise above.
- **Unified entry** for **text and voice** into one turn pipeline.
- Single mode flag: `local` | `online` (default `local`).
- Online path **B**: context inject → ChatGPT Voice → conversation in client
  (voice modality); online **text** inject+send when modality=text.
- Control plane from **transcript / turn text** (controller + keyword + timeouts).
- Graceful **degraded** operation when DOM/transcript scrape fails.
- Opt-in module; no OpenAI API key required for this surface.
- Fit module discipline (bootc + ansible render, `verify.sh`, no secrets in tree).

**Non-Goals:**

- Realtime API / paid audio tokens as transport.
- Stable OpenAI-compatible proxy over the web client.
- WebKit-first shell; Electron reimplementation of ChatGPT.
- Silent auto-switch local→online on errors.
- v0 full agent tool callbacks from ChatGPT text.
- **Standalone micro-apps** that open ChatGPT without mode/actions/status
  integration (violates prime premise).

## Decisions

### D0 — Aggregator hub first, then slots/packs

*Chosen:* Implement a **modular aggregator** first (turn pipeline, mode,
context slot, control slot, action bus, status, entry adapters), then
register backends and feature packs as plugins. No pack merges until it
registers on the aggregator.

*Alternatives:* Ship independent scripts per idea (rejected — user
requires mutual integration); mega-monolith without pack boundaries
(rejected — unmaintainable); smart entrypoints that each re-implement
routing (rejected — duplicates, no single brain).

*Why:* User wants a large modular aggregator in the middle so all targets
compose; entry stays thin, backends stay replaceable.

### D0b — Unified entry point for text and voice

*Chosen:* One user-facing entry family (name TBD: `aipc-assistant` /
`aipc chat` / extend `aipc-voice-once` into a general turn tool) that
accepts:

| Modality | How |
|---|---|
| **text** | `aipc-assistant --text "…"` / stdin / short REPL |
| **voice** | existing PTT / side button → STT → same turn path |
| **online voice** | mode=online → inject + ChatGPT Voice (path B) |
| **online text** | mode=online → inject user text + send (no Voice), scrape reply (path A-online) |

Internal shape:

```text
TurnRequest {
  modality: text | voice
  text: optional  # filled by user or STT
  session_id: optional
  prefer: auto | local | online   # optional override of mode file
}
TurnResponse {
  text: optional   # local /chat or scraped online reply
  mode_used: local | online
  actions: [...]   # controller/keyword side effects
}
```

`aipc-voice-once` becomes a **voice entry adapter** that records → STT →
`TurnRequest` into the **aggregator**. Text users hit the same aggregator
without mic. Control slot (model + keywords) runs on `text` either way.

**Online text vs online voice:** aggregator routes modality=voice +
mode=online to path B; modality=text + mode=online to inject+send
(optional scrape). User can request voice after text via action.

*Alternatives:* Separate `aipc-chatgpt` only for online and leave local
text on raw curl to :4100 (rejected — splits UX); voice-only entry
(rejected — user wants text).

*Why:* One surface; modality is input plumbing; **routing lives in the
aggregator**, not in each adapter.

### D1c — One web engine, many site packs (config + LLM setup)

*Chosen:* The browser layer is a **shared Playwright Chromium engine** with
**pluggable site packs** (first pack: `chatgpt`). `sites.yaml` declares
enabled sites, URLs, pack module paths, auth method, and setup hints.
First-run / setup uses **config rules + optional local LLM**
(`setup_judge.plan_setup` → `resident-small`) to decide next steps
(`install_playwright`, `auth_login`, `ready`) and user-facing copy — not a
ChatGPT-only hard-coded wizard.

```text
WebEngine (one Chromium)
   ├─ sites/chatgpt.py   inject/voice/login detect
   ├─ sites/claude.py    (future)
   └─ sites/*.py
sites.yaml  →  registry  →  engine.use(site_id)
```

Per-site profile + storage_state under `aipc-web/sites/<id>/`.
Aggregator `backend.online` defaults to `default_site` from config.

*Why:* User requirement in one line — modularize; same engine, many sites;
setup via config + LLM judgment.

### D1b — Login session collection (owned browser, no password store)

*Chosen:* Because the wrapper owns Chromium, authentication is captured as:

1. **Persistent `user_data_dir`** under `$XDG_DATA_HOME/aipc-chatgpt/profile`
   (normal browser cookie/localStorage lifetime).
2. **Portable `storage_state.json`** (Playwright cookies + origins), mode
   `0600`, path `$XDG_DATA_HOME/aipc-chatgpt/storage_state.json`.
3. CLI: `aipc-chatgpt auth login|status|export|import` — **manual login in
   the headed window**; tool only waits, detects logged-in UI, and exports.

**Never** store email/password in repo or plaintext config. Optional backup
via SOPS-encrypted storage_state off-machine.

*Why:* User asked to collect login info from the packaged browser; session
export is the secure, automatable form.

### D1 — Transport: aipc-owned Chromium wrapper (not system Chrome)

*Chosen:* Ship a **dedicated web-engine wrapper** owned by
`modules/assistant-chatgpt/`:

- **Engine:** Chromium family **bundled or pinned** by the module
  (preferred: Playwright-managed Chromium / chrome-for-testing, or a
  small Electron/CEF shell). Same major capabilities as desktop Chrome
  for `chatgpt.com` Voice + WebRTC.
- **Profile:** isolated under aipc paths
  (e.g. `/var/lib/aipc-chatgpt/profile` or `$XDG_DATA_HOME/aipc-chatgpt/`),
  never the user's daily browser profile.
- **Control plane:** CDP or in-process Playwright on **127.0.0.1 only**
  (inject, voice controls, transcript scrape, `session_close`).
- **Window:** app-like single site (`chatgpt.com`); `session_close`
  disposes the wrapper process/window without wiping the profile.

**Explicit non-dependency:** v0 MUST NOT require Flatpak Google Chrome,
host `google-chrome`, or attaching to an already-running user browser.
System Chrome may be used only as an **optional emergency override** in
config for debugging, not as the default.

*Alternatives:*

| Option | Pros | Cons |
|---|---|---|
| System Flatpak/host Chrome + CDP (spike) | Fast to demo; real login already there | **User rejected for production** — updates, Flatpak sandbox `/tmp`, profile fights, "哪天就被炸" |
| WebKitGTK / Tauri system WebView | Light | Voice/WebRTC on Linux often weaker; diverges from ChatGPT's Chrome testing |
| Electron full app shell | Clean window chrome, easy packaging | Heavier image; still Chromium underneath |
| Playwright-launched Chromium | Engine version pinned to bridge; good CDP; no Google Chrome package | Need mic/display wiring; download size |
| Realtime API | Stable protocol | Paid API; user wants subscription client |

*Preferred implementation order:*

1. **Playwright (or equivalent) launches pinned Chromium** headed, persistent
   context dir, expose control API as `aipc-chatgpt` (lowest glue for
   inject/selectors already proven on CDP).
2. If product wants a "real app window" later, wrap the same profile in
   Electron/CEF without changing the keyword/mode contracts.

*Why:* Automation surface stays under aipc version control; user browser
can update/break independently; spike on Flatpak Chrome only proved the
**protocol** (inject, mic, orb, close), not the shipping host process.

### D2 — Online UX path B (Voice) as default; text path as fallback

*Chosen:* Default online turn: session inject (if needed) → `voice_start`.
If Voice control cannot be located, fall back to text inject of a short
status message and notify the user (do not fake success).

*Alternatives:* Online-text-only (STT → inject → scrape → local TTS): more
aipc-native but loses the naturalness goal. Hybrid always-scrape-reply: brittle.

*Why:* User priority is subscription Voice feel; automation sits on top.

### D3 — Transcript as the automation bus

*Chosen:* While Voice is active, a watcher emits `TranscriptEvent{role,text,ts}`.
Keyword rules and idle detection consume this stream. Inject deltas can also
be triggered by topic keywords in the stream.

*Alternatives:* Timer-only stop; hotkey-only stop; audio VAD on system mic
without DOM (doesn't know "結束語音" content).

*Why:* User asked for keyword auto-close and inject driven by 逐字稿.

### D4 — Keyword rules: config YAML, user-side default, cooldowns

*Chosen:* Ship `/etc/aipc/assistant/keywords.yaml` with user override under
`$XDG_CONFIG_HOME/aipc/assistant/keywords.yaml`. Default `on: user` only.
Actions: `voice_stop`, `mode_local`, `session_close`, `inject_session`,
`inject_delta`. Per-rule `cooldown_s`.

**End commands close the window:** Default phrases such as「結束語音」
「關掉語音」「結束通話」「關閉助理」map to `session_close` (stop Voice
best-effort, then CDP `page.close()` / exit app window). `mode_local`
SHALL also close the window then write mode=`local`. Bare `voice_stop`
remains available for power users who want to keep the window open, but
is **not** the shipped default for end phrases.

Spike (2026-07-10, this host): `page.close()` on Flatpak Chrome `--app`
tore down the window and dropped CDP (`ECONNREFUSED` on :9222). Profile
cookies remain for next launch when `user-data-dir` is durable.

*Alternatives:* Hardcoded Chinese-only phrases; LLM classifies intent
(latency + local model dependency for online path); only mute Voice and
leave window (user rejected — wants end → close window).

*Why:* Editable, testable, no extra model on the critical stop path;
matches user expectation that "結束" dismisses the online assistant shell.

### D5 — Mode storage and voice entry branch

*Chosen:* Mode file `/etc/aipc/assistant/mode` (system default `local`) with
optional user override file; CLI `aipc assistant mode`. `aipc-voice-once`
reads mode at start: `online` → `aipc-chatgpt turn --voice`, else existing
pipeline.

*Alternatives:* Env-only; only D-Bus state; route inside `:4100` graph.

*Why:* Voice entry already bypasses complex agent routing; file+CLI is
debuggable and matches other `/etc/aipc/*` knobs. Keeps `:4100` free of
DOM/CDP dependencies.

### D6 — Context inject content (v0 minimal)

*Chosen:* Session bundle = assistant persona name (if set) + local datetime
timezone + optional mem0 top-k short facts (soft-fail if mem0 down).
v1: `POST :4100/context` and topic deltas (calendar/files).

*Alternatives:* Dump full mem0/RAG (token bloat, privacy); no inject (weaker
binding to aipc).

*Why:* Enough for "bound to aipc" without building full context API first.

### D7 — Modular layout: aggregator module + online backend packs

*Chosen:* Split conceptually into:

1. **`modules/assistant-aggregator/`** (or `assistant-core`) — the **super
   aggregator**: turn pipeline, mode, context/control/action slots, entry
   CLI (`aipc-assistant`), status. Depends on LiteLLM for controller;
   talks to local `:4100` and online backend via interfaces.
2. **`modules/assistant-chatgpt/`** — **online backend + web packs**
   (engine, session, inject into chatgpt.com, voice, transcript scrape,
   optional project/gpt/…). Implements `backend.online` for the
   aggregator.

v0 may co-locate both under one tree if packaging is easier, but **code
boundaries must match the two layers** so local-only hosts can run the
aggregator without the Chromium backend.

```text
modules/assistant-aggregator/          # hub (required for unified entry)
  files/usr/bin/aipc-assistant
  files/usr/lib/aipc-assistant/
    aggregator/     # pipeline orchestrator
    slots/mode context control actions status
    entry/          # text + voice adapters
    backends/       # local client, online client interfaces
  files/etc/aipc/assistant/
    mode, features.yaml, keywords.yaml, controller.yaml, inject-policy.yaml

modules/assistant-chatgpt/             # online backend (optional .disabled)
  files/usr/lib/aipc-chatgpt/
    engine/ session/ inject/ voice/ transcript/
    features/{handoff, system_audio, project, gpt, upload, canvas, capture, tasks}
```

**Slot/pack contract:**

```text
name, slot: entry|control|context|backend|output|pack
enabled: features.yaml
commands: { … }                 # aipc-assistant <cmd> / feature …
hooks: on_turn_start | on_control | on_transcript | on_turn_end
run(action|turn) → Result
verify() → 0|2|fail
```

**CLI shape:**

```text
aipc-assistant status
aipc-assistant --text "…"              # unified entry
aipc-assistant mode local|online
aipc-assistant feature list|enable|disable <name>
aipc-assistant online inject "…"       # pass-through to online backend
aipc-assistant online session close
# voice: aipc-voice-once → aggregator entry (adapter)
```

**Enablement:**

| Layer | Default |
|---|---|
| Aggregator | ships with assistant surface; mode `local` |
| Online backend module | `.disabled` until hardware-verified |
| Optional packs | off until implemented |

*Alternatives:* Everything only in `assistant-chatgpt` (blurs hub vs
backend); everything only in voice-pipecat (wrong ownership); per-feature
top-level modules (catalog explosion).

*Why:* User asked for a large modular aggregator in the middle; online
web is one backend among others.

### D8 — Process model

*Chosen:* Aggregator CLI is the short-lived turn runner; optional user
daemon holds **online engine+session** and streams transcript events back
to the aggregator when online. Control/context are in-process libraries.
Packs load with the process that owns their resources (audio graph with
online daemon, etc.).

*Alternatives:* Always-on system service (wrong session/mic/display);
one daemon per pack (noise); pure shell (no continuous transcript).

*Why:* Hub orchestrates; online backend may outlive a single CLI invoke.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| ChatGPT DOM/Voice UI changes break selectors | Versioned selector table; `transcript: degraded`; keyword automation disables; idle/max timeout + manual stop remain |
| CDP port exposed on LAN | Bind 127.0.0.1 only; document firewall; refuse start if bind != loopback |
| User not logged in | `status` reports `auth: needed`; turn aborts with notify-send; no spin loop |
| System Chrome update breaks automation | **Default is aipc-owned engine**; pin Chromium revision with the module |
| Engine download / image size | Prefer Playwright browser cache or module asset; document offline bake for bootc |
| OpenAI ToS / automation grey area | Personal opt-in; no headless farm; no multi-account; stop on demand |
| Privacy: conversation leaves machine | Explicit `online` mode; default no mem0 write-back; redact list in inject-policy |
| Conflicts with local voice mic | Online Voice uses system default mic in wrapper; document "one voice consumer at a time"; local PTT idle when online session active |
| System-audio feedback / echo | Dedicated wrapper sink excluded from monitor mix; default mic-only |
| Privacy: desktop audio to cloud | Opt-in allow; session revoke on close; status shows active share |
| Module bloat / maintenance | Thin wrapper + pinned engine; no fake OpenAI API; ship disabled until verified |

## Migration Plan

1. Land module `.disabled` + docs + mode defaults `local` (no behavior change).
2. Hardware: create profile dir, manual login once, enable module, set mode online, exercise Voice + keyword stop.
3. Wire `aipc-voice-once` branch behind mode file (safe when module absent: treat as local).
4. Rollback: `aipc assistant mode local` and/or re-disable module; remove user unit; leftover Chrome profile is inert data.

### D10 — Local → online handoff by spoken command (v1; not v0 gate)

*Chosen:* While assistant mode is **`local`**, the local pipeline (STT text
from `aipc-voice-once` / future always-on) SHALL be able to recognise
configured **handoff phrases** and transfer work to the online ChatGPT
path instead of (or after a short ack from) `:4100/chat`.

```text
local STT transcript
      │
      ├─ match handoff phrase?  ──yes──► set mode=online (session or sticky)
      │                                    inject optional remainder as context
      │                                    aipc-chatgpt turn --voice
      │                                    notify「已切到網上助理」
      │
      └─ no ──► existing local /chat → TTS
```

**Phrase classes (user-editable YAML, same family as online keywords):**

| Intent | Example phrases (zh/en) | Action |
|---|---|---|
| Switch online + Voice | 「網上助理」「用 ChatGPT」「切到語音 ChatGPT」「online mode」 | `mode_online` + `turn --voice` |
| One-shot online then back | 「問一下 ChatGPT…」+ remainder | online turn; on `session_close` return `local` |
| Sticky online | 「之後都用網上助理」 | `mode=online` until user says return-local |

**Remainder handling:** If the utterance is `「用 ChatGPT 幫我解釋 X」`, strip
the trigger and inject `X` (or full utterance) into the ChatGPT session
before/while starting Voice so the user does not repeat themselves.

**v0:** Manual `aipc assistant mode online` / mode file only — no STT
handoff. Avoids coupling local STT false positives to cloud opens.

**v1:** Enable handoff behind `handoff.enabled: true` in
`/etc/aipc/assistant/inject-policy.yaml` (or `keywords.yaml` section
`local_to_online`). Default off until hardware-proven.

*Alternatives:* Always route every local turn through a classifier LLM
(cost/latency); only CLI switch (user wants spoken handoff later);
open ChatGPT without mode change (orphans aipc state).

*Why:* Symmetric with online → local keyword close; one voice button, two
brains, spoken routing.

### D12 — NPU-first: entire hub runnable on resident-small

*Chosen:* The assistant **hub** (control, setup judgment, **local chat
fulfillment**) is designed to run on the **always-on NPU model**
`resident-small` (`gemma4-it-e4b-FLM` via LiteLLM → Lemonade) **without
loading Vulkan 35B models** (ornith / coder-agentic / assistant-gemma).

| Path | Model / compute |
|---|---|
| Control (intent → actions) | `resident-small` JSON-in-content |
| Setup plan (`sites plan`) | `resident-small` |
| Local mode chat | `resident-small` via LiteLLM (default) |
| Agent `:4100` (tools, Daily Assistant) | **Optional** (`local_backend.mode: agent\|auto`) |
| Online mode conversation | ChatGPT subscription web (no local LLM) |
| Online DOM automation | Playwright CPU; not an LLM |

Config: `runtime.yaml` (`npu_first: true`, `local_backend.mode: npu`).
Control `allow_models: [resident-small]` prevents accidental large-model
routing. Prefer **JSON in content**, not OpenAI `tools` API, for NPU FLM.

*Why:* User wants architecture that runs on the resident NPU fleet path;
iGPU slots stay free for coding models when not needed.

```text
transcript / local STT
        │
        ▼
  controller pack
        │  POST LiteLLM chat  model=resident-small
        │  → structured JSON { action, pack?, args?, confidence }
        │
        ├─ confidence ≥ threshold ──► actions pack (session_close, …)
        │                              or feature pack command
        └─ model down / low conf / timeout
                 └── keywords.yaml rules (deterministic fallback)
```

**What the local model controls (examples):**

| Input | Example decisions |
|---|---|
| Local STT | handoff to online? sticky vs one-shot? remainder text? |
| Online user transcript | end session? mode_local? allow system audio? |
| Online assistant transcript | (usually ignore for safety; optional) |
| User command CLI free text | which pack command to run |

**Contract (structured, not free-form shell):**

```json
{
  "action": "session_close" | "mode_local" | "mode_online" | "voice_stop"
           | "inject_delta" | "feature_enable" | "feature_run" | "none",
  "pack": "handoff" | "system_audio" | "project" | null,
  "args": {},
  "confidence": 0.0,
  "reason": "short"
}
```

Actions are **allow-listed**; the model cannot invent shell commands.
Invalid JSON / unknown action → treat as `none` and fall back to keywords.

**Why not only keywords:** paraphrases (「可以關掉了」「先這樣吧」) and
pack routing (「打開某某 project」) need light NLU; small local models
already in the fleet fit this better than growing a phrase list forever.

**Why not ornith-35b / coder-agentic by default:** control plane must stay
fast and must not fight the user for Vulkan slots during online Voice;
`resident-small` on NPU is the right tier. Document config
`controller.model: resident-small` overridable to `qwythos-9b` if needed.

**v0:** Keywords-only is acceptable to ship Voice; controller pack can
land v0.5/v1 as soon as structured JSON is hardware-verified on
`resident-small` (NPU tool_calls were previously weak — prefer **JSON in
content**, not `tools` API, for this alias).

*Alternatives:* Keywords only (user wants model control); cloud classifier
(rejected for control plane); full agent with unrestricted tools
(rejected — blast radius).

*Why:* Matches host inventory and LiteLLM contract (CLAUDE.md §7).

### D11 — Optional system-audio share into the online wrapper (exclude self-voice)

*Chosen:* The online wrapper's capture path MAY include **desktop/system
audio** in addition to the microphone, so ChatGPT Voice can hear media,
calls, or games playing on the machine. This is **off by default** and
only enabled under an explicit allow (config and/or per-session grant).

**Must exclude the assistant's own playback** (ChatGPT Voice TTS / wrapper
output). Feeding its own speech back causes echo, runaway interruption,
and garbage transcript. Implementation on PipeWire/Pulse:

```text
                    ┌─ mic ─────────────────────────────┐
 other apps' sinks ─┤                                   ├─► virtual source
                    │  monitor of "everything else"     │   "aipc-chatgpt-in"
                    └─ NOT monitor of wrapper sink ─────┘         │
                                                                  ▼
                                                         Chromium default input

 wrapper / ChatGPT audio out ──► dedicated sink "aipc-chatgpt-out"
                                 (speakers/headphones; not looped to in)
```

| Mode | Default | When |
|---|---|---|
| `mic_only` | **yes** | Normal talk |
| `mic_plus_system` | no | User allows system share for this session or sticky allow |
| `system_only` | no | Rare; document if ever exposed |

**Allow model ("看情況允許"):**

1. Config `audio.system_share: off | ask | on` (default `off` or `ask`).
2. Runtime: `aipc-chatgpt audio system allow --session 30m` / keyword
   「分享系統聲音」with confirmation; revoke on `session_close` when
   session-scoped.
3. Status must show whether system share is active (privacy surface).
4. Never silently enable on mode online alone.

**v0:** Mic only is enough to ship Voice; system-share can land v1 once
wrapper sink naming is stable. Design locks the product rule early so
audio graph work is not improvised later.

*Alternatives:* Always share system audio (privacy/echo risk — rejected);
Chrome tab-capture only (misses other apps); raw full monitor including
self (feedback — rejected).

*Why:* User wants ChatGPT to hear the desktop when useful, under control,
without hearing itself.

### D9 — Headed v0; headless is a future opt-in (not v0)

*Chosen:* v0 runs **headed** Chrome/Chromium (`--app`, real display
session) so ChatGPT Voice, mic permission UI, and WebRTC behave like the
subscription client the user already uses.

**Future (v1/v2, not blocking v0):** optional `display: headless | xvfb |
headed` in assistant config.

| Mode | Feasibility notes |
|---|---|
| True `--headless=new` | Often **breaks** or degrades Voice/WebRTC/mic; ChatGPT may treat as bot; **not** the path for "natural Voice". |
| Xvfb / virtual display | **Likely best "headless-ish"** for automation: real Chromium graphics stack, no user-visible window; mic still needs PipeWire/Pulse path. |
| Headed (default) | Proven on this host with CDP inject + Voice orb + mic grant. |

Headless must still use a **persistent profile**, loopback CDP only, and
the same keyword → `session_close` semantics. First-login and first mic
grant may still require a one-time headed session.

*Alternatives:* Force headless-only v0 (rejected — Voice spike needs display);
always show window (v0 default — accepted).

*Why:* User wants headless later for integration cleanliness; product goal
remains subscription Voice quality, so virtual display beats true headless.

## Web-only product surface (wrapper roadmap)

ChatGPT **product** features that live primarily on `chatgpt.com` / apps
and are **not** replaceable by the platform API under a subscription
login. The aipc wrapper is justified as automation over this surface.

Legend: **Web-only / product** = needs DOM/client; **API-ish** = could
be done with platform keys (user rejected for this path); **Hybrid** =
possible both ways with different quality/cost.

### Tier A — Why the wrapper exists (product Voice + account brain)

| Capability | Notes | Wrapper automation ideas |
|---|---|---|
| **GPT-Live / ChatGPT Voice** | Consumer S2S; subscription quotas; not “use my Plus via API” | `voice_start/stop`, transcript scrape, keyword close (v0) |
| **Voice + memory + search + widgets** | Live voice can use memory, web search, visual cards (weather/stocks/…) inside product | After voice, scrape cards/links; inject “use memory” prefs via UI |
| **Account Memory (personalization)** | Saved facts UI at settings; project-only memory options | Open memory settings; export/list via UI scrape (fragile); inject “remember that…” turns |
| **Custom instructions / personality** | Product personalization, not Assistants API | Open settings; set once per profile |
| **Subscription entitlements** | Plus limits, model picker, priority | Detect plan banner; fail soft if free caps hit |

### Tier B — Workspace / organization (mostly web UI)

| Capability | Notes | Wrapper ideas |
|---|---|---|
| **Projects** | Files, chats, project instructions, shared projects; context scoped to project | Navigate to project URL; new chat in project; upload file dialog; switch project by name |
| **Chat history / search** | Sidebar history, search conversations | Open chat by title; search; continue thread |
| **Canvas** | Side-by-side doc/code editor in product | Open canvas; inject text; extract final doc (DOM) |
| **Custom GPTs** | GPT Store / my GPTs; tools & knowledge in product UI | Launch GPT by URL/slug; voice-with-GPT if UI allows |
| **Scheduled Tasks (Tasks / Pulse)** | Proactive reminders; hub on **web & mobile** (not all desktop apps) | Create/list/pause tasks via UI; notify user when OpenAI fires (hard—may need webhooks or poll UI) |
| **File / image upload** | Attach to chat; DALL·E / image gen in product | CDP file chooser / drag path into upload control |
| **Plugins / apps / connectors** | Product-side integrations | Click enable; only where UI exposes |

### Tier C — Multimodal “see with me” (client-heavy)

| Capability | Notes | Wrapper ideas |
|---|---|---|
| **Voice + live camera** | Often app-first; desktop web may lag | Future: grant camera to wrapper; start video voice UI |
| **Voice + screen share** | Advanced Voice legacy path; GPT-Live launch said video/screen later | Future: feed display capture into client if UI supports; else **system-audio share (D11)** + screenshots inject as images |
| **Screenshot / paste image** | Always works on web | Hotkey → capture region → inject as attachment (aipc-owned, reliable) |

### Tier D — Explicitly not the wrapper’s job

| Capability | Why |
|---|---|
| Cheap bulk completions | Platform API / LiteLLM local aliases |
| Stable tool-calling agents | `:4100` / LangGraph, not DOM |
| Offline assistant | Local voice path |
| Guaranteed selectors forever | DOM will break; degraded mode required |

### Suggested wrapper command surface (future, not v0 scope)

```text
aipc-chatgpt turn --voice              # v0
aipc-chatgpt inject "…"
aipc-chatgpt session_close
aipc-chatgpt project open <name>       # v2
aipc-chatgpt gpt open <slug>           # v2
aipc-chatgpt upload <path>             # v1/v2
aipc-chatgpt canvas extract            # v2
aipc-chatgpt tasks list|create …       # v2 (fragile)
aipc-chatgpt memory note "…"           # via chat inject, not settings scrape
aipc-chatgpt capture screen|region     # v1 hybrid with D11 audio
```

Implementation rule: **prefer inject-into-chat** over settings-page
scraping when both work (more stable). Reserve deep settings automation
for rare setup wizards.

## Open Questions

1. Pin mechanism for Chromium: Playwright browser download vs vendored tarball in image — resolve in module packaging task.
2. Whether v0 includes any `inject_delta` topics or only session inject + stop rules (proposal allows v0 minimal; prefer stop rules first).
3. Exact default Chinese/English keyword list — start from design table in tasks, user-editable after.
4. Integration with `agent-gate` `cloud-api` scope — recommend session grant later; not blocking v0 if mode is already explicit.
5. Headless backend when implemented: Xvfb vs engine headless — prefer Xvfb unless proven otherwise.
6. Handoff default: sticky `mode=online` vs one-shot online-then-local — prefer one-shot for privacy unless user says sticky phrase.
7. Electron shell vs Playwright window only for v0 UX — prefer Playwright first if Voice works; Electron if window management needs it.
8. System-audio graph: PipeWire module-loopback vs pw-link script — pick during v1 audio task on this host.
9. Controller JSON schema versioning; confirm `resident-small` on NPU returns stable JSON without tool_calls API.
