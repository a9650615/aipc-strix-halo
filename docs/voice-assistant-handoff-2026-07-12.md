# Voice Assistant — Session Handoff (2026-07-12)

Branch: `phase-3-voice-assistant-2026-07-08`. Author of this work:
`claude-opus-4-8`. This session did the "Siri-like but smarter" assistant
overhaul + a long stretch of live voice debugging. It documents what is solid,
what is deployed-but-needs-tuning, the exact live tweaks in place, and the
open items — so a successor (or the user at the machine) can continue without
re-deriving context.

> **Honest framing:** the voice/acoustic layer (wake-word STT accuracy, the
> on-screen listening indicator) was debugged blind — no mic, no eyes — via
> logs and X11 window sampling. Several judgement calls missed the user's
> real experience, and repeated service restarts destabilised a working
> system. Those items are flagged **NEEDS HANDS-AT-THE-MIC** below; do not
> keep blind-patching them.

---

## 1. Solid + verified (software layer — trust these)

| Area | Commit | Verification reached |
|---|---|---|
| Persistent task registry + reap orphaned Hermes on boot | `34cabe7`, `16429a1` | Live: a real Hermes turn registered in `/var/lib/aipc-agent/task_jobs.json` with pid/pgid; reap PID-reuse guard confirmed (non-hermes pid not killed) |
| Session-bound proactive task follow-up (notify once on completion) | `21f413b` | Hermetic unit test on deployed bytes (submit→persist→followup→ack-once) |
| "查任務" routing — `還有哪些任務在跑 / 在忙什么 / 任务进度` | `b2cbdc5` | Live: 4 phrasings hit `job_status` in 0.0–0.1s |
| Turn-state contract (`done`/`reply`/`end`, background ack) | `4f487bf`, `dea9d8b`, `fff4b4e`, `948d4bc` | API-tier: `/chat` returns `expect_reply`/`background`/`end_session` correctly |

## 2. Deployed + logic correct, but NEEDS HANDS-AT-THE-MIC tuning

| Area | Commit | Status / open question |
|---|---|---|
| Overlay dock model: **active→centre, idle→hidden, bg_task→right pill, short result→right, rich→centre** | `45a91a1`, `a91df75` | Log + X11 geometry confirm recording centres at the screen midpoint and idle hides. **User still perceives "wake → straight to 執行中, no 錄音中"** — could NOT be reproduced from logs: at 05:07 the wake fired and `recording` (錄音中) showed for ~3s before processing. Needs the user to describe/record the on-screen reality. |
| Overlay flicker (idle orb repaint on fractionally-scaled monitor) | `935c6bd` | User-confirmed fixed |
| Overlay single launcher (removed duplicate KDE autostart) | `8735235` | Verified single window; build-enables the user service via `default.target.wants` symlink |
| Wake-word denoise off | `ca5c55f` + live drop-in | Wake works but is **flaky** (see §4) |

## 3. Live state on this machine (not all in git)

- Services (real unit names): `litellm`, `lemonade`, `aipc-resident-small`,
  `aipc-agent-orchestrator`, `aipc-voice-wake`, `aipc-voice-stt-sensevoice`,
  `aipc-mem0` active; `aipc-voice-overlay` (user) active. NOTE the LLM units
  are `litellm.service`/`lemonade.service` (NO `aipc-` prefix) — the
  `aipc-litellm`/`aipc-lemonade` names are inactive/legacy, do not be fooled.
- Live drop-in: `/etc/systemd/system/aipc-voice-wake.service.d/denoise-off.conf`
  (sets `AIPC_WAKE_DENOISE=0`). Now also baked into the repo unit (`ca5c55f`);
  the drop-in is redundant after a rebuild — safe to delete then.
- F20 hotkey: KDE global shortcut `aipc-voice-once.desktop=F20` → runs
  `/usr/local/bin/aipc-voice-once` (synced to current). `/usr/bin/aipc-voice-once`
  does NOT exist (read-only ostree); the live binary is `~/.local/bin` (wake
  uses this via `AIPC_VOICE_ONCE=`) and `/usr/local/bin` (F20 uses this).
- Deployed-live Python (byte-identical to repo): overlay, wake, voice-once,
  and orchestrator `task_jobs.py`/`graphs.py`/`server.py`/`intent_classifier.py`.

## 4. Open items — fine-tune at the machine

1. **Wake-word STT flakiness (NEEDS EARS).** Same setup: SenseVoice
   transcribes `嘿助理` sometimes correctly (`hit='嘿助理'`), sometimes as
   `我。` / `嗯。` (miss). Denoise-off (`AIPC_WAKE_DENOISE=0`) improved it but
   did not make it reliable. Levers to try at the mic: `AIPC_WAKE_CAPTURE_S`
   (short 2s window may clip the phrase), mic gain, SenseVoice accuracy on the
   short phrase, or adding more `phrase_hit` fuzzy variants in
   `aipc_voice_wake.py`.
2. **"Wake → straight to 執行中" (NEEDS EYES).** Logs show `recording` is
   written for ~3s on a successful wake, yet the user sees only 執行中. Get a
   screen recording. Suspect if confirmed: the orchestrator pushes `working`
   via the priority overlay API while the wake writes `recording` via the
   legacy file writer (`aipc_voice_ux.write_status`, no priority) — two writers
   on `$XDG_RUNTIME_DIR/aipc-voice-state.json` with no coordination; the
   API/priority push may win. Fix would be to give the active-capture state
   authority over a late background `working` push, or unify the two writers.
3. **Simple queries mis-route to heavy Hermes** (e.g. `今天几月` → hermes,
   long 執行中). This is the capability router (`router/analyze.py` /
   task #6 巨型 context→35B) — **owned by the concurrent model worker**, not
   this session. Flag to them.

## 5. Debug recipes that worked (reuse these)

- **Overlay is geometry/opacity/map stable but "flickers"** → it's a content
  repaint. Sample the X11 window at high freq to rule out positioning first:
  `xdotool getwindowgeometry --shell <wid>` + `xwininfo -id <wid> | grep
  IsViewable` in a tight loop. The idle orb `update()` was the culprit.
- **State-transition trace** (what the overlay shows during a turn): poll
  `/run/user/1000/aipc-voice-state.json` every 50ms, log on change. Correlate
  with `journalctl -u aipc-voice-wake`.
- **Turn-state / routing at the service tier** (no mic): POST to
  `http://127.0.0.1:4100/chat` with urllib (curl is intercepted by
  context-mode) and inspect `expect_reply`/`background`/`end_session`/`text`.
- **job_status keyword lists are triplicated** — `graphs.wants_job_status`,
  `intent_classifier.rules_classify` status_keys, and the AUTHORITATIVE
  `router/analyze.py` `_JOB_RE`. Only the router copy is consulted live; edit
  `router/analyze.py` FIRST when changing intent routing.

## 6. Operational cautions (things this session got wrong — don't repeat)

- **Never restart `aipc-agent-orchestrator` while a turn is in flight**
  (overlay=`working` or a hermes process alive): the Hermes subprocess escapes
  the service cgroup via `runuser` and orphans. Check for in-flight in a
  SEPARATE step BEFORE restarting, not the same command.
- Orphaned/`--resume` Hermes processes that were never registered in the store
  are NOT caught by `reap_orphans_on_startup` — kill by process group manually
  (`kill -TERM -<pgid>`), verify `/proc/<pid>/cmdline` contains `hermes` first.
- `register_proc(pid)` fills the store's pid a few seconds AFTER submit (once
  Hermes spawns); polling within ~2s shows `pid=None` — a timing artifact, not
  a bug.

## 7. Do NOT touch (concurrent worker's files)

`modules/system-aipc-portal/**`, `dashboard.py`, `index.html`, `index.astro`,
`test_control_center_spa.py`, `memory-mem0/**`, `daily_assistant.py`,
`llm-litellm/**`, `llm-lemonade/**`, `llm-models/**`, `dev-ai-codexbar-gui/**`,
`router/analyze.py`'s model/routing weights, and the capability-router
context-cap logic (task #6). The branch has this worker's WIP uncommitted;
merge timing is the 大哥's/user's call.
