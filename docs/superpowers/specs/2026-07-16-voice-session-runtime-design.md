# Voice Session Runtime Design

Date: 2026-07-16  
Status: draft for user review  
Approach: **Session Runtime** (phased full redesign; not Pipecat rewrite)  
Related: `docs/voice-pipeline.md`, `docs/voice-runtime-flow.md`,  
`docs/superpowers/specs/2026-07-08-aipc-voice-assistant-design.md`,  
`openspec/changes/phase-3-voice/`, live diagnosis 2026-07-16

## 1. Problem

The always-on voice assistant is daily-usable in pieces but **not trustworthy**:

1. **Ghost activity** — UI jumps up then vanishes without a real user call  
   (ambient energy → STT `我。` fuzzy-mapped to 嘿助理 → short VAD cut → junk dismiss).
2. **Configuration archaeology** — 15+ systemd drop-ins under  
   `aipc-voice-wake.service.d/` override each other by filename sort order  
   (`zzzz-eos-cut` beat `zzz-cmd-eos-relax`, then `zzzzzz-*` patches again).
3. **God-object runtime** — `aipc_voice_wake.py` (~2.5k LOC) owns wake, VAD,  
   progressive STT, junk policy, follow-up, ducking, UX, and turn dispatch.
4. **Three sources of truth** — ostree `/usr/lib/aipc-voice/`, live hotfix  
   `/var/lib/aipc-voice/lib/`, and repo `modules/voice-*` drift.
5. **Latency and resource fights** — optional heavy models / SMO admission can  
   stall the voice path; TTS unit thrash (orphan container vs systemd) is a  
   deployment footgun. Voice quality is secondary this cycle; stability is not.

Product vision (closed loop mic → STT → intent/chat → TTS) stays.  
This design rebuilds the **control plane and session runtime**, not the product story.

## 2. Goals and non-goals

### Goals (priority)

| Rank | Goal | Success means |
|------|------|----------------|
| 1 | **Reliability** | No ghost flash; intentional sessions complete or clear reprompt |
| 1 | **Maintainability** | One config; testable state machine; `aipc voice doctor` prints effective config |
| 2 | **Latency** | After reliability, cut end-of-speech → first audio/text feedback |
| 3 | **Capability** | Multi-turn, tools, true wake-word — only after stable runtime |
| Last | **Voice/TTS quality** | Functional speech out; persona/timbre out of scope this design |

### Explicit product rules (from brainstorming)

1. **Wake policy A+C**  
   - Clear phrase (e.g. real 嘿助理 / long enough match) or PTT / control center → enter session.  
   - Fuzzy / noise priors (e.g. STT-only `我。`, length < 2 CJK, particle-only) → **do not open command UI**. Prefer miss over ghost jump.
2. **Smart follow-up**  
   - After a successful reply, arm “listen for continuation” in the background.  
   - Background-only noise → **no UI flash**. Real speech → capture carefully.  
   - Timeout → idle without drama.
3. **Intentional unclear capture**  
   - User deliberately started a turn, but STT is junk/empty → short **「沒聽清」** (text first; TTS optional) → one re-listen window → then idle.
4. **Never silent-vanish after intentional arm**  
   - Ghost path never arms. Intentional path always ends in reply, reprompt, or explicit idle with reason in logs.

### Non-goals

- Full Pipecat graph rewrite as the first delivery.
- CosyVoice persona polish, clone training UX, or TTS A/B quality work.
- Replacing SenseVoice/Kokoro with new model families (unless a phase needs a thin adapter).
- Changing the LiteLLM public model namespace or bypassing the gateway for chat.
- Gaming overlay / multi-display special cases beyond not breaking them.

## 3. Architecture

### 3.1 Target shape

```text
                    ┌─────────────────────────────┐
   mic frames ───►  │  voice-capture (VAD/STT)    │
                    └─────────────┬───────────────┘
                                  │ events
                    ┌─────────────▼───────────────┐
   PTT / hotkey ──► │  voice-session (state machine)│◄── config.yaml
   control center   │  pure transitions + policy    │
                    └─────────────┬───────────────┘
                       │          │          │
              UX events│     turn jobs│   metrics│
                       ▼          ▼          ▼
                 voice-ux    voice-turn    journal/JSONL
                 (overlay)   (once/stream
                              intents/chat
                              TTS best-effort)
```

**Single orchestrator process** (initially still the wake unit binary, refactored in-place; optionally later a named `aipc-voice-session` service) owns the state machine. Capture and turn workers are libraries or subprocesses with clear contracts.

### 3.2 State machine

States:

| State | UI | Mic | Notes |
|-------|----|-----|--------|
| `IDLE` | hidden / listening hint only if user enabled always-hint | energy/phrase **classifier only** | No command capture |
| `WAKE_CANDIDATE` | none (or debug-only) | short buffer | Internal; not user-visible |
| `ARMED` | wake / “請說指令” | command capture | Only after **clear** wake or PTT |
| `CAPTURING` | recording | command VAD + progressive STT | |
| `RESOLVING` | thinking | optional hold | STT final + front-gate + intent/chat |
| `REPROMPT` | “沒聽清” | re-open capture once | Intentional arm only; max 1 auto reprompt per arm |
| `SPEAKING` | speaking | optional echo gate | TTS best-effort; text always |
| `FOLLOWUP_ARMED` | **no flash** on noise | background energy/STT probe | UI only if speech committed |
| `FOLLOWUP_CAPTURING` | recording | same as CAPTURING | Entered only on real speech |

Primary transitions:

```text
IDLE
  --clear_wake|ptt--> ARMED --> CAPTURING
  --fuzzy_or_noise--> IDLE          # no UI
  --energy_only-----> WAKE_CANDIDATE --> (clear phrase? ARMED : IDLE)

CAPTURING
  --usable_utterance--> RESOLVING
  --timeout_empty-----> REPROMPT (if intentional) else IDLE
  --junk_stt-----------> REPROMPT (if intentional) else IDLE

RESOLVING
  --reply-------------> SPEAKING --> FOLLOWUP_ARMED or IDLE
  --local_intent------> SPEAKING/action --> FOLLOWUP_ARMED or IDLE
  --error-------------> UX error --> IDLE

FOLLOWUP_ARMED
  --bg_noise_only-----> stay / expire --> IDLE   # no UI
  --real_speech-------> FOLLOWUP_CAPTURING
  --timeout-----------> IDLE

REPROMPT
  --second_fail-------> IDLE
  --usable------------> RESOLVING
```

`intentional` is true for: clear wake, PTT, control center, KRunner explicit ask.  
`intentional` is false for: fuzzy STT alias alone, pure energy without phrase confirm.

### 3.3 Components

| Unit | Responsibility | Must not do |
|------|----------------|-------------|
| **voice-session** | State, policy, timeouts, turn lifecycle, config load | Raw model inference |
| **voice-capture** | arecord/PipeWire, RMS/VAD, progressive STT client | Decide dismiss/UX |
| **voice-wake-gate** | Phrase match tiers: `clear` / `fuzzy` / `none` | Open overlay by itself |
| **voice-turn** | intents, `/chat` or stream, TTS router, notify | Own global mic loop |
| **voice-ux** | Overlay + optional notify from state events | Policy |
| **voice-config** | Load/merge/validate one YAML; export effective dump | Runtime side effects |
| **voice-doctor** | Units, ports, effective config, drift vs repo, recent ghost metrics | Fix automatically without flag |

Existing modules map as:

- `voice-wake` → session host + wake-gate + capture (split files over phases)
- `voice-pipecat` → voice-turn (`aipc-voice-once` / `aipc-voice-stream`)
- `voice-stt-*` / `voice-tts-*` → unchanged service boundaries
- `voice-audio-front` → optional signal into RESOLVING; cannot alone dismiss intentional usable text

### 3.4 Configuration (single source of truth)

**Canonical file:** `/etc/aipc/voice/config.yaml`  
**Shipped from:** `modules/voice-wake/files/etc/aipc/voice/config.yaml` (or a small `voice-config` fragment owned by voice-wake).  
**User override:** `/etc/aipc/voice/config.d/*.yaml` merged last-wins by sorted name — **not** systemd drop-ins for policy knobs.

Illustrative schema (normative fields; defaults chosen for anti-ghost):

```yaml
version: 1
wake:
  phrases: ["嘿助理", "hey assistant"]
  energy_min: 2200
  cooldown_s: 8
  # STT aliases: only upgrade to clear if length/confidence rules pass
  fuzzy_aliases:
    "我": { maps_to: "嘿助理", tier: fuzzy }   # never arms alone
  clear_min_cjk: 3                             # 嘿助理 = 3
  require_clear_for_arm: true
capture:
  end_silence_ms: 1300
  end_silence_fast_ms: 950
  min_speech_ms: 850
  max_s: 18
  junk_particles: ["我", "嗯", "啊", "。"]
followup:
  enabled: true
  arm_s: 12
  silence_s: 2.6
  post_tts_s: 0.9
  ui_on_noise: false           # critical: no flash
  speech_commit_ms: 400        # energy before showing UI
  junk_max: 2
session:
  reprompt_on_intentional_junk: true
  reprompt_text: "沒聽清，請再說一次"
  max_reprompts: 1
turn:
  chat_model: resident-small
  stream: true
  use_aggregator: false
tts:
  enabled: true
  required: false              # text path always wins
observability:
  jsonl_path: /var/log/aipc/voice-turns.jsonl
```

**Migration:** collapse all current `aipc-voice-wake.service.d/*` policy Environment lines into this YAML. Unit retains only process identity (User, XDG_RUNTIME_DIR, PYTHONPATH, EnvironmentFile pointing at generated env **or** Python reads YAML directly). After migration, drop-in directory should contain **zero** policy knobs (at most sleep-resilience Restart=).

### 3.5 Wake gate tiers

| Tier | Example | Result |
|------|---------|--------|
| `clear` | Transcript normalizes to 嘿助理 / 你好助理 / hey assistant with length OK | → ARMED |
| `fuzzy` | `我。`, single particle, STT garbage historically mapped to wake | **stay IDLE** (optional debug counter) |
| `none` | Unrelated speech | IDLE |

Historical alias “嘿助理 misheard as 我。” is **kept only as diagnostic documentation**, not as an auto-arm rule. If hardware later proves a high-precision secondary signal (openWakeWord score, second-pass STT), it may promote fuzzy→clear under an explicit config flag `wake.allow_fuzzy_promote: false` by default.

PTT / control center / KRunner force `clear` intentional arm without phrase STT.

### 3.6 Follow-up behavior (“smart context”)

1. After successful SPEAKING (or silent local action), enter `FOLLOWUP_ARMED`.
2. Capture path runs a **probe**: energy + optional partial STT.
3. If probe classifies noise/junk → do not call UX show; remain armed until timeout.
4. If probe commits speech → `FOLLOWUP_CAPTURING` + show recording UI.
5. Usable utterance → RESOLVING as a continuation turn (`expect_reply` / session_id as today).
6. Farewell / `end_session` from turn API → IDLE (existing turn-state contract preserved).

### 3.7 Turn and models

- Default chat model remains **`resident-small`** via LiteLLM (or direct `:4100/chat` as today’s closed-loop default).
- Voice session **must not** trigger exclusive 122B loads.
- Admission / SMO: voice tier is **reserved**; floating/exclusive agent models cannot unload the pinned resident path needed for voice (implementation detail may live in litellm scheduler + `aipc-resident-small`; design requirement is “voice turn p95 not blocked by agent model swap”).
- Streaming turn remains optional feature flag; failure falls back to once.

### 3.8 Deployment and drift

| Layer | Role |
|-------|------|
| Repo `modules/voice-*` | Source of truth for image |
| Ostree `/usr` | Immutable shipped code |
| `/var/lib/aipc-voice` | **Discouraged** for long-lived forks; allowed only as version-stamped hotfix with `aipc voice doctor` drift warning |
| `/etc/aipc/voice/` | Config (local overrides OK) |

`aipc voice doctor` reports: unit active, ports (9001/8880/4100), effective config dump, last N turn outcomes, ghost_wake_count estimate, code path in use (usr vs var).

Kokoro (and other quadlets): single owner of the port; unit must not thrash if a container already healthy (notify + health, or `podman run --replace` only when health fails). Separate from session logic but **P0 ops fix** because restart storms hurt the machine.

## 4. Data flow (happy vs anti-ghost)

### Happy (clear wake)

```text
energy → STT phrase clear → ARMED UI → CAPTURING → usable text
  → RESOLVING → chat/intent → SPEAKING (text±TTS) → FOLLOWUP_ARMED
  → user speaks → FOLLOWUP_CAPTURING → …
  → quiet → IDLE
```

### Ghost (must not show UI)

```text
ambient energy → STT "我。" → tier=fuzzy → IDLE
  (metric: ghost_suppressed++)
```

### Intentional junk

```text
PTT/clear wake → CAPTURING → junk → REPROMPT "沒聽清" → CAPTURING
  → junk again → IDLE
```

## 5. Observability

Each terminal outcome appends one JSON line:

```json
{
  "ts": "...",
  "session_id": "...",
  "state_path": ["IDLE","ARMED","CAPTURING","RESOLVING","SPEAKING","FOLLOWUP_ARMED","IDLE"],
  "arm_reason": "clear_wake|ptt|followup|fuzzy_suppressed",
  "stt_wake": "我。",
  "stt_cmd": "现在几点",
  "usable": true,
  "outcome": "ok|reprompt|junk_idle|timeout|error|ghost_suppressed",
  "ms": {"wake": 0, "capture": 0, "llm": 0, "tts": 0, "total": 0}
}
```

Success metrics (hardware):

- Ghost UI shows per hour → near zero with normal room noise.
- Intentional clear-wake completion rate (reply or reprompt, not silent dismiss) → ≥ 95% in lab script.
- `aipc voice doctor` effective config matches YAML (no surprise env).

## 6. Testing strategy

| Tier | What |
|------|------|
| Static | Unit tests for state transitions, wake tier, junk classifier, config merge |
| Render | Module ships single config; systemd unit has no policy drop-in pile; bootc/ansible parity |
| Hardware | Fixture WAVs: (1) ambient-only, (2) 嘿助理+现在几点, (3) intentional empty, (4) follow-up real speech, (5) follow-up noise |

Hardware fixtures are mandatory before claiming ghost-fixed.

## 7. Phased delivery

### Phase P0 — Anti-ghost + config truth (fastest user relief)

- Implement wake tier: fuzzy never arms UI.
- Collapse drop-ins → `config.yaml` + thin unit.
- Intentional junk → reprompt text (TTS optional).
- Turn JSONL + doctor effective config.
- Stop Kokoro restart storm pattern (ops).
- **Exit:** ghost flash rare; doctor dump trusted.

### Phase P1 — State machine extraction

- Refactor wake loop into explicit states listed in §3.2.
- FOLLOWUP_ARMED without UI-on-noise.
- Capture module boundary; unit tests for transitions.
- **Exit:** no silent vanish on intentional path; follow-up not scary.

### Phase P2 — Runtime consolidation

- once/stream share voice-turn library.
- Drift detection usr vs var; prefer image path.
- Latency instrumentation (existing backlog) wired to JSONL.
- Voice vs SMO reservation for resident-small.
- **Exit:** one turn path; p95 latency baseline recorded.

### Phase P3+ — Capability (out of critical path)

- Real openWakeWord / trained phrase on NPU.
- Richer multi-turn memory UX.
- Cosy primary TTS when stable.
- Optional Pipecat **behind** the same session events (adapter), not a rewrite of policy.

## 8. Error handling

| Failure | Behavior |
|---------|----------|
| STT down | Intentional: error UX + IDLE; do not loop |
| Chat down | Error text; no hang forever (hard timeout) |
| TTS down | Text/notify only (`tts.required: false`) |
| Mic open fail | Error + IDLE; restart unit via systemd |
| Overlay dead | Journal + notify fallback; session continues |
| Config invalid | Refuse start with clear stderr; keep last-good if configured |

## 9. Migration plan (live machine)

1. Ship YAML with defaults matching **desired** anti-ghost policy (not the 750ms eos-cut).
2. Generate or read config from session process; remove policy drop-ins in same change.
3. Keep one emergency override: `AIPC_VOICE_CONFIG=/path` for debug.
4. Do not delete `/var/lib/aipc-voice` hotfixes until doctor reports zero drift or hotfixes merged to repo.
5. Document in `docs/voice-runtime-flow.md` as the new locked-in flow after P1.

## 10. Open decisions (resolved in this doc)

| Topic | Decision |
|-------|----------|
| Approach | Session runtime, phased; not full Pipecat rewrite |
| Ghost vs miss | Prefer miss; fuzzy does not arm |
| Follow-up | Smart arm, no UI on noise |
| Unclear intentional | 沒聽清 + one reprompt |
| TTS priority | Best-effort; not a gate |
| Scope of this design | Full v2; implement P0→P2 first |

## 11. Out of scope leftovers

- Control-center SPA redesign.
- mem0 quality / portal features.
- 122B coding agent behavior (except “must not break voice”).
- Bluetooth A2DP recovery (separate design already exists).

## 12. Acceptance checklist (design-level)

- [ ] User agrees §2 product rules and §7 phases.
- [ ] Implementation plan breaks P0 into concrete tasks/files.
- [ ] No new `zzzz*.conf` policy knobs introduced after P0.
- [ ] Ghost path has a named metric and a hardware fixture.

## 13. Implementation plan handoff

After this design is approved, create an implementation plan (writing-plans) starting with **P0 only** as the first PR-sized plan, with P1/P2 outlined as subsequent plans so work stays reviewable.
