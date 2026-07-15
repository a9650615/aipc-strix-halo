# Voice Session Runtime Design

Date: 2026-07-16  
Status: **revised for user review** (v2 — multi-agent deep review folded in)  
Approach: **Session Runtime** (phased full redesign; not Pipecat rewrite)  
Related: `docs/voice-pipeline.md`, `docs/voice-runtime-flow.md`,  
`docs/superpowers/specs/2026-07-08-aipc-voice-assistant-design.md`,  
`openspec/changes/phase-3-voice/`, live diagnosis 2026-07-16

**Review method:** four parallel critiques (code vs design, anti-ghost scoring,
UX “not scary” contract, module/phasing stress test). This revision treats
P0 as a **behavior inversion** of live policy, not a config cleanup alone.

## 1. Problem

The always-on voice assistant is daily-usable in pieces but **not trustworthy**:

1. **Ghost activity** — UI jumps up then vanishes without a real user call  
   (ambient energy → STT `我。` **auto-armed** via `_MANGLED_WAKE` in  
   `phrase_hit()` → short VAD cut → junk dismiss hide).
2. **Configuration archaeology** — 15+ systemd drop-ins under  
   `aipc-voice-wake.service.d/` override each other by filename sort order.
3. **God-object runtime** — `aipc_voice_wake.py` (~2.5k LOC) owns wake, VAD,  
   progressive STT, junk policy, follow-up, ducking, UX, and turn dispatch.
4. **Three sources of truth** — ostree `/usr/lib/aipc-voice/`, live hotfix  
   `/var/lib/aipc-voice/lib/` (unit **ExecStart already points here**),  
   and repo `modules/voice-*`.
5. **Live policies that look like knobs but lie** — e.g. `FOLLOWUP_JUNK_MAX`  
   is read and incremented but **never compared** (always dismiss on first junk).  
   `FOLLOWUP_DIRECT=1` immediately shows recording UI after every reply.
6. **Latency / resource fights** — heavy models / SMO; Kokoro unit thrash  
   when orphan container holds `:8880`. TTS quality is secondary; stability is not.

Product vision (closed loop mic → STT → intent/chat → TTS) stays.  
This design rebuilds the **control plane and session runtime**, not the product story.

### 1.1 Root cause (ghost jump) — precise

```text
energy gate open
  → STT often "我。"
  → phrase_hit: hay in _MANGLED_WAKE + phrases contain 助理 → ARMS as 嘿助理
  → _ux(wake) + _ux(recording)          ← UI flash (scary)
  → command VAD ends with junk "。"/"我。"
  → _drop_empty_capture → hide          ← vanish
```

Hardware note (2026-07-16): SenseVoice maps real spoken 嘿助理 to `我。` as well.  
Therefore **text-only ban of `我` kills true wake**. Anti-ghost needs  
**multi-signal promote**, not “never map 我” alone.

## 2. Goals and non-goals

### Goals (priority)

| Rank | Goal | Success means |
|------|------|----------------|
| 1 | **Reliability** | No ghost flash; intentional sessions complete or clear reprompt |
| 1 | **Maintainability** | One config; testable policy; doctor prints effective config + code path |
| 2 | **Latency** | After reliability, cut EOS → first text/audio feedback |
| 3 | **Capability** | Multi-turn polish, tools, true wake-word — after stable runtime |
| Last | **Voice/TTS quality** | Functional speech out; persona/timbre out of scope |

### Explicit product rules

1. **Wake policy A+C (refined)**  
   - **Clear text** (phrase length OK) or **PTT / control center / KRunner** → arm UI.  
   - **Fuzzy text alone** (`我。`, particles) → **never open command UI**.  
   - **Fuzzy + acoustic promote score ≥ threshold** (optional, default on for this host) → arm as `fuzzy_promoted` (intentional). Prefer miss over ghost if score low.
2. **Smart follow-up**  
   - After successful reply, arm background probe only.  
   - Noise/junk → **zero UI**. Real speech ≥ `speech_commit_ms` → show recording.  
   - Do **not** use overlay state `followup` as a permanent “可接話” card (live SHOW is a scare source).
3. **Intentional unclear capture**  
   - `intentional=true` + junk/empty → text **「沒聽清，請再說一次」** (TTS optional) → **one** re-listen → then idle.  
   - Never silent-vanish after intentional UI was shown.
4. **Prefer miss over ghost**  
   - Metric `ghost_suppressed` may rise; `ghost_ui_shows` must stay ~0 in normal rooms.

### Intentional sources (normative)

`intentional = true` only for:

- `clear_wake`
- `fuzzy_promoted` (acoustic promote passed)
- `ptt` / control center / KRunner explicit
- follow-up path after a prior intentional success (`followup_committed` speech)

`intentional = false` for: pure energy, fuzzy suppressed, candidate expired.

### Non-goals

- Full Pipecat rewrite as first delivery.
- CosyVoice persona polish / clone training UX.
- Replacing SenseVoice/Kokoro families in P0–P1.
- Bypassing LiteLLM for chat.
- Gaming overlay special cases beyond not breaking them.

## 3. Architecture

### 3.1 Target shape

```text
                    ┌─────────────────────────────┐
   mic frames ───►  │  voice-capture (VAD/STT)    │
                    └─────────────┬───────────────┘
                                  │ events
                    ┌─────────────▼───────────────┐
   PTT / hotkey ──► │  voice-session (policy + SM) │◄── config.yaml
   control center   │  single status writer        │
                    └─────────────┬───────────────┘
                       │          │          │
              UX events│     turn jobs│   metrics│
                       ▼          ▼          ▼
                 voice-ux    voice-turn    JSONL (+ privacy timing)
                 (overlay)   (once/stream)
```

P0–P1 remain **one process** (today’s wake unit), refactored in place under  
`modules/voice-wake`. No new module for config.

### 3.2 State machine

| State | Overlay token | UI visible? | Notes |
|-------|---------------|-------------|--------|
| `IDLE` | `listening` (status only) | **no** (unless always-hint) | |
| `WAKE_CANDIDATE` | none / debug | **no** | fuzzy medium score; extend buffer |
| `ARMED` | `wake` | yes (≥600ms min) | clear / promote / PTT |
| `CAPTURING` | `recording` | yes | |
| `RESOLVING` | `thinking`/`working` | yes (≥400ms min) | |
| `REPROMPT` | `no_speech` | yes (≥1.5s hold) | intentional only; max 1 |
| `SPEAKING` | `speaking`→`done` | yes | text always; TTS best-effort |
| `FOLLOWUP_ARMED` | **not** live `followup` SHOW | **always hidden** | probe only |
| `FOLLOWUP_CAPTURING` | `recording` | yes | after speech_commit |
| `MUTED` | optional one-shot toast | no ongoing | phrase wake off; PTT may still work |
| `error` | `error` | yes (≥2s) | |

Primary transitions:

```text
IDLE
  --clear_text|ptt---------------> ARMED --> CAPTURING
  --fuzzy + score>=promote-------> ARMED (if allow_fuzzy_promote)
  --fuzzy + medium score---------> WAKE_CANDIDATE (no UI)
  --fuzzy/low|noise|none---------> IDLE (ghost_suppressed)

WAKE_CANDIDATE
  --clear re-STT|speech_commit---> CAPTURING (UI only after commit)
  --timeout quiet----------------> IDLE

CAPTURING
  --usable-----------------------> RESOLVING
  --junk|empty + intentional-----> REPROMPT (once) else IDLE
  --timeout start + intentional--> REPROMPT

REPROMPT
  --usable-----------------------> RESOLVING
  --second fail------------------> IDLE (no second 沒聽清 spam)

RESOLVING
  --reply------------------------> SPEAKING
  --end_session (rc=2)-----------> IDLE
  --background (rc=4)------------> IDLE + bg_task pill (turn owns)
  --error------------------------> error --> IDLE

SPEAKING
  --tts_end + post_tts_gate------> FOLLOWUP_ARMED (UI hide)
  --farewell---------------------> IDLE

FOLLOWUP_ARMED
  --noise|junk partial-----------> stay (no UI)
  --speech_commit----------------> FOLLOWUP_CAPTURING
  --timeout arm_s----------------> IDLE silent
  --ptt----------------------------> CAPTURING intentional

FOLLOWUP_CAPTURING
  --usable-----------------------> RESOLVING
  --junk-------------------------> IDLE (no REPROMPT spam by default)

Any state
  --mute flag--------------------> cancel capture; IDLE/MUTED
  --session lock-----------------> force IDLE; stop TTS; hide UI
  --barge PTT while SPEAKING-----> cancel TTS; CAPTURING intentional
```

#### Turn outcome fan-in (preserve live once contract)

| once/stream rc / fields | Session action |
|-------------------------|----------------|
| success + expect_reply / default after speak | FOLLOWUP_ARMED |
| `end_session` / rc=2 | IDLE |
| background detach / rc=4 | IDLE + allow `bg_task` UX from turn |
| error | error UX → IDLE |

Deprecate open-ended `FOLLOWUP_ALWAYS` env: policy is “smart follow-up after SPEAKING unless end_session/farewell”.

### 3.3 Multi-signal wake gate (replaces §3.5 sketch)

**Principle:** fuzzy text alone never arms UI; clear text arms; fuzzy needs acoustic promote.

#### Text tier `classify_text(transcript) → clear | fuzzy | none`

| Tier | Rule |
|------|------|
| `clear` | Norm matches phrase / multi-char alias (≥3 CJK or known multi-char slips like 嗨助理); **not** bare particles |
| `fuzzy` | Norm in `{我,我呀,我啊,嘿,嗨,黑,咯,咳,…}` or weak SequenceMatcher band |
| `none` | Unrelated |

**P0 code change:** remove `_MANGLED_WAKE` auto-return of phrase in `phrase_hit`  
(`modules/voice-wake/.../aipc_voice_wake.py` ~331–341 and live twin).

#### Acoustic score (0–100) on wake PCM

Signals (no new ML): `speech_ms`, `peak_ratio` vs noise floor, `duty`, duration band  
(~280–1400ms for wake word), optional `audio_front` accept/ignore, playback veto.

Hard veto: speech_ms < ~180ms; high-conf audio_front ignore; pure playback bleed.

#### Decision matrix

| text | score | action | UI | arm_reason |
|------|-------|--------|-----|------------|
| clear | not veto | ARM | yes | `clear_wake` |
| fuzzy | ≥ promote (default 62) and `allow_fuzzy_promote` | ARM | yes | `fuzzy_promoted` |
| fuzzy | medium | WAKE_CANDIDATE | **no** | — |
| fuzzy | low | IDLE | no | `ghost_suppressed` |
| none | — | IDLE | no | — |
| PTT | — | ARM | yes | `ptt` |

Defaults for this host: `allow_fuzzy_promote: true` (recover 嘿助理→`我。`),  
`promote_score: 62`, `candidate_window_s: 1.2`, `speech_commit_ms: 350–400`.

Lab gate: ambient 10–30 min ghost UI ≈ 0; spoken 嘿助理 with STT forced/`我。` arm ≥ 90% of 20 trials when promote on.

### 3.4 Follow-up modes

| Mode | Behavior | Default |
|------|----------|---------|
| `probe` (design) | FOLLOWUP_ARMED hidden; UI only after speech commit | **on** |
| `direct` (legacy) | Immediate recording UI after post_tts (live `FOLLOWUP_DIRECT=1`) | **off** after P0/P1 |

Live `followup` overlay SHOW + “可接話” card is **retired** for session policy.  
Teaching multi-turn belongs in onboarding/control center, not every-turn flash.

`followup.junk_max`: either implement real N-fail before IDLE in P1, or **delete**  
from schema until implemented (do not reify dead knobs).

### 3.5 Components and modules

| Unit | Module | P0–P1 action |
|------|--------|--------------|
| voice-session + wake-gate + capture | `voice-wake` | In-process refactor |
| voice-config loader | `voice-wake` (`aipc_voice_config.py`) | **No new module** |
| voice-turn | `voice-pipecat` (once/stream) | Minimal; inject env from session |
| voice-ux | `voice-pipecat` overlay | Mapping only; avoid large 0014 conflict |
| STT/TTS | existing | Unchanged contracts |
| Kokoro thrash | `voice-tts-kokoro` | **Parallel P0-ops track**, not merge-blocker for anti-ghost |

### 3.6 Configuration (single source of truth)

**Canonical:** `/etc/aipc/voice/config.yaml`  
**Shipped:** `modules/voice-wake/files/etc/aipc/voice/config.yaml`  
**Overrides:** `/etc/aipc/voice/config.d/*.yaml` (sorted last-wins)  
**Debug:** `AIPC_VOICE_CONFIG=/path`  
**Deprecate:** `modules/voice-wake/files/etc/aipc/wake/config.yaml` stub; keep  
`/etc/aipc/wake/phrases` via `wake.phrases_file` or migrate lists into YAML.

#### Precedence (hard rule — anti half-migration)

```text
AIPC_VOICE_CONFIG file
  → /etc/aipc/voice/config.d/*.yaml
  → shipped config.yaml
  → (optional) built-in defaults in code
```

**Policy env / systemd drop-in knobs are not read after P0-B.**  
Doctor **FAIL** (or hard WARN) if `aipc-voice-wake.service.d/*` still contains  
`AIPC_WAKE_CMD_*` / `AIPC_WAKE_FOLLOWUP_*` / `AIPC_WAKE_ENERGY` after migration.

Identity-only unit env may remain: `User`, `XDG_RUNTIME_DIR`, `PYTHONPATH`,  
`AIPC_VOICE_ONCE` path, DBUS/PULSE.

#### Illustrative schema (normative fields)

```yaml
version: 1
wake:
  phrases: ["嘿助理", "hey assistant"]
  phrases_file: /etc/aipc/wake/phrases   # optional
  energy_min: 2200
  cooldown_s: 8
  clear_min_cjk: 3
  allow_fuzzy_promote: true
  promote_score: 62
  candidate_score: 42
  candidate_window_s: 1.2
  hard_min_speech_ms: 180
  wake_speech_ms_min: 280
  wake_speech_ms_max: 1400
  use_audio_front_for_wake: true
capture:
  end_silence_ms: 1300
  end_silence_fast_ms: 950
  min_speech_ms: 850
  max_s: 18
  text_stable_s: 1.4
followup:
  enabled: true
  mode: probe                 # probe | direct
  arm_s: 12
  silence_s: 2.6
  post_tts_s: 0.9             # from actual TTS end when possible
  speech_commit_ms: 400
  ui_on_noise: false
session:
  reprompt_on_intentional_junk: true
  reprompt_text: "沒聽清，請再說一次"
  max_reprompts: 1
  pause_on_lock: true
  barge_ptt_cancels_tts: true
turn:
  chat_model: resident-small
  stream: false               # opt-in until hardware-verified; live may set true
  use_aggregator: false
tts:
  enabled: true
  required: false
ux:
  armed_min_visible_ms: 600
  resolving_min_visible_ms: 400
  reprompt_hold_ms: 1500
  error_hold_ms: 2500
  followup_show_ui: false
  earcon_on_wake: false       # less startling
observability:
  timing_jsonl: /var/lib/aipc-voice/log/turns.jsonl   # no transcripts (privacy)
  debug_jsonl: /var/log/aipc/voice-session-debug.jsonl  # optional; may include text
  debug_jsonl_enabled: false
```

#### Normative defaults note

Live effective stack (2026-07-16 after zzzzzz-assistant-hear) already uses  
~1300ms EOS. Design freezes anti-ghost-friendly numbers; **do not** resurrect  
750ms `zzzz-eos-cut`. Stream default in **docs** is off; live may be on —  
schema default **false** until verified; override in config.d if needed.

### 3.7 UX contract (not scary)

> **UI only proves:** you clearly called me / I am recording your utterance /  
> I have an answer or “沒聽清” / hard error.  
> **UI never proves:** I am guessing in the background.

| Rule | Detail |
|------|--------|
| Ghost path | Zero SHOW writes (no `miss` flash, no `detecting`, no wake) |
| Intentional latch | Once intentional UI shown → terminal must be reply / reprompt / error / logged idle |
| Single status writer | Session owns status.json; turn emits events only (P1 hard requirement; P0 reduce dual-write) |
| Min visible | armed ≥600ms, resolving ≥400ms, reprompt ≥1.5s, error ≥2s |
| FOLLOWUP_ARMED | Always hidden |
| Mute | At most one toast; no loop |
| Lock | `pause_on_lock`: stop TTS, hide, IDLE |

### 3.8 Edge cases (must not drop on extraction)

- Barge-in: PTT during SPEAKING cancels TTS → new CAPTURING; phrase wake during CAPTURING does not nest sessions.
- Mute flag mid-capture clears to IDLE.
- Suspend/resume: recalibrate noise; reconnect arecord (existing resilience).
- Background `rc=4` / `bg_task` pill must not force listening flash.
- Audio-front ignore cannot dismiss intentional **usable** progressive text (live override kept).
- Miss-streak energy thr inflation must not deafen real wake after ghosts suppressed (do not thr-raise on fuzzy_suppressed).
- KRunner/hotkey arm as intentional without phrase STT.
- Stream failure → once fallback without second UI jump.
- Overlay dead → notify fallback; session continues.
- Headphones / multi-sink: TTS best-effort; duck non-TTS streams; doctor shows default sink (P1+).

### 3.9 Deployment and drift

| Layer | Role |
|-------|------|
| Repo `modules/voice-*` | Image source of truth |
| Ostree `/usr` | Immutable shipped code |
| `/var/lib/aipc-voice` | Hotfix only; **version stamp**; doctor warns if sha ≠ usr |
| `/etc/aipc/voice` | Config overrides |

P0 hardware claims require confirming **running code path** (often `/var/lib` today)  
actually contains the new tier logic — not only that repo is green.

Kokoro: single port owner; health-based restart; parallel PR-E.

## 4. Data flow

### Happy (clear or promoted)

```text
energy → classify+score → ARMED UI → CAPTURING → usable
  → RESOLVING → SPEAKING (text±TTS) → post_tts → FOLLOWUP_ARMED (hidden)
  → real speech commit → FOLLOWUP_CAPTURING → …
  → quiet → IDLE
```

### Ghost (must not show)

```text
ambient → STT "我。" → fuzzy + low/mid score → IDLE or WAKE_CANDIDATE expire
  metrics only
```

### Intentional junk

```text
clear/PTT → CAPTURING → junk → REPROMPT ≥1.5s → CAPTURING → junk → IDLE
```

## 5. Observability

**Two logs:**

1. **Privacy timing** (existing `aipc_voice_timing` style): durations, outcomes, **no** raw transcripts by default.  
2. **Debug session JSONL** (opt-in): may include `stt_wake` / `stt_cmd` / scores for lab.

Metrics: `ghost_suppressed`, `ghost_ui_shows` (target ~0), `fuzzy_promoted`,  
`intentional_silent_dismiss` (target 0), `reprompt_count`.

Doctor prints: effective YAML dump, code path + sha, residual policy drop-ins,  
ports (9001/8880/4100), recent outcome histogram, Kokoro health/restarts.

## 6. Testing

| Tier | Coverage |
|------|----------|
| Static | `classify_text`, score fixtures, transition pure functions, config merge, repo unit has **zero** policy drop-ins, verify.sh |
| Render | bootc + ansible parity for config + thin unit |
| Hardware | Fixtures below before any “ghost fixed” claim |

### Hardware / fixture matrix

| ID | Scenario | Expect |
|----|----------|--------|
| G1 | Room ambient 10–30 min | No UI flash |
| G5 | Noise WAV + forced STT `我。` | No arm (regression for old phrase_hit) |
| T1 | Spoken 嘿助理 (STT may be 我。) | Arm ≥90% lab with promote |
| T2 | 嘿助理 + 现在几点 | Full reply or clear error |
| I1 | Intentional + silence | 沒聽清 once, not silent vanish |
| F1 | Follow-up noise only | 0 SHOW frames |
| F2 | TTS playing, mic bleed | No false CAPTURING |
| L1 | Screen lock mid-session | Hide + stop TTS |

## 7. Phased delivery (PR-sized)

OpenSpec change name (recommended): **`0019-voice-session-runtime`**  
(`why/what/how/tasks` + link to this design; do not dual-write specs).

### P0 product milestone — five PRs (same change, sequenced)

| PR | Name | Touch (repo) | Exit |
|----|------|--------------|------|
| **A** | Anti-ghost wake tier | `aipc_voice_wake.py` phrase path; `tools/tests/test_voice_wake_tier.py` | Unit: 我。→fuzzy; ambient logic documented |
| **B** | Config truth | `etc/aipc/voice/config.yaml`, `aipc_voice_config.py`, thin unit; **atomic** kill policy drop-ins in deploy | Doctor effective == YAML; no dual-read env |
| **C** | Intentional REPROMPT | `_drop_empty_capture` policy; tests | Intentional junk never silent vanish |
| **D** | JSONL + doctor | log helper; `tools/aipc_lib/doctor.py` | Trusted dump + outcomes |
| **E** | Kokoro thrash (parallel) | `voice-tts-kokoro` only | Port single owner; no restart storm |

**First writing-plan / first merge:** **PR-A only.**

Hardware “feels fixed” needs at least A + live code path updated + policy drop-ins cleared.  
Full P0 exit: A+B+C + doctor D + clean drop-ins.

### P1 — State machine extraction

- Explicit states §3.2; FOLLOWUP probe mode default.  
- Single status writer; barge/mute/lock tables implemented.  
- Capture module boundary + transition unit tests.  
- Overlay: never SHOW on FOLLOWUP_ARMED; retire 可接話 card.

### P2 — Runtime consolidation

- once/stream share turn library.  
- Prefer `/usr` ExecStart; clear var drift or stamp hotfixes.  
- Latency fields in timing JSONL.  
- Voice reservation vs SMO exclusive models for resident-small.

### P3+ — Capability

- openWakeWord / NPU secondary score.  
- Richer multi-turn memory.  
- Cosy primary when stable.  
- Optional Pipecat **adapter** behind same events.

## 8. Error handling

| Failure | Behavior |
|---------|----------|
| STT down | Intentional → error UX; no loop |
| Chat down | Error text; hard timeout |
| TTS down | Text only |
| Mic fail | Error + systemd restart |
| Overlay dead | Notify; session continues |
| Invalid config | Refuse start; clear stderr |
| Command start timeout intentional | REPROMPT not silent IDLE |
| Lock | Force IDLE, stop TTS |

## 9. Migration plan (live machine)

1. Ship PR-A into **the path the unit actually runs** (`/var/lib` and/or `/usr`).  
2. PR-B: install YAML; **same deploy** delete policy drop-ins; daemon-reload; restart wake.  
3. Doctor must FAIL residual policy drop-ins.  
4. Do not leave dual-read “YAML + env legacy” as permanent mode.  
5. Rollback = revert PR + known-good drop-in archive — never re-stack new zzzz.  
6. After P1, mark `docs/voice-runtime-flow.md` superseded banner → new flow.

## 10. Decisions log

| Topic | Decision |
|-------|----------|
| Approach | Session runtime phased; not Pipecat rewrite |
| Ghost vs miss | Prefer miss; multi-signal promote for 嘿助理↔我。 |
| Follow-up | probe default; no UI on noise; retire SHOW `followup` card |
| Unclear intentional | 沒聽清 ×1 |
| TTS | Best-effort; not a gate |
| Config owner | `voice-wake` module; no `voice-config` module |
| P0 shape | Five PRs A–E; first plan = A |
| OpenSpec | `0019-voice-session-runtime` |
| Stream default | false in schema until HW verified |
| junk_max | Implement or omit; no dead knobs |
| Status writer | Session-owned (hard in P1) |

## 11. Out of scope leftovers

- Control-center SPA redesign.  
- mem0 / portal features.  
- 122B agent behavior except must not break voice.  
- Bluetooth A2DP (separate design).

## 12. Acceptance checklist

- [ ] User agrees product rules + multi-signal wake + UX “no promise → no UI”.  
- [ ] User agrees P0 = PR-A…E with first implementable unit = PR-A.  
- [ ] Implementation plan for PR-A written after approval.  
- [ ] No new `zzzz*.conf` policy knobs after P0-B.  
- [ ] Hardware fixtures G1/G5/T1/I1 before “ghost fixed” claims.  
- [ ] Doctor reports code path used for verification.

## 13. Implementation plan handoff

On design approval:

1. Open `openspec/changes/0019-voice-session-runtime/` linking this doc.  
2. Invoke **writing-plans** for **PR-A (anti-ghost wake tier)** only.  
3. Outline PR-B…E as subsequent plans.

## 14. What multi-agent review changed (v1 → v2)

| Gap in v1 | v2 fix |
|-----------|--------|
| Fuzzy never arm vs STT always `我。` for real wake | Multi-signal promote + WAKE_CANDIDATE |
| Follow-up “no flash” vs live FOLLOWUP_DIRECT + overlay SHOW | probe mode; ban SHOW on FOLLOWUP_ARMED |
| REPROMPT not in code; silent dismiss | Intentional latch + REPROMPT ×1 |
| junk_max dead knob | Implement or delete |
| P0 too large as one PR | Split A–E; first = A |
| Config vs unit ExecStart `/var/lib` | Doctor path/sha; migrate carefully |
| Missing barge/mute/lock/rc | Edge tables in SM |
| Privacy vs debug JSONL | Dual log |
| Stream default contradiction | Schema false; opt-in |
| Kokoro as merge blocker | Parallel PR-E |

---

**Bottom line for implementers:** P0 is a deliberate **behavior break** of  
`_MANGLED_WAKE` auto-arm and of silent intentional dismiss — plus config  
truth — not “collapse drop-ins” alone. Without acoustic promote, anti-ghost  
will feel like “助理聾了”. Without live path + drop-in atomic cleanup,  
repo green means nothing on this host.
