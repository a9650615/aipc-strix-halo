# proposal: assistant-self-improvement

## Why

The closed-loop assistant already has short-term dialogue buffer, mem0
storage, and ad-hoc “internalize” hooks — but it still behaves like a
**stateless tool-router with a scrapbook**, not a system that **keeps
getting better at this user’s life**. After multi-turn teaching
(“查股價用 Hermes”), the next session can still deny tools or re-ask the
same things. Keyword routing and one-shot `infer` writes are not a
self-improvement loop.

We need an explicit **自我精進** layer: observe → extract → consolidate →
evaluate → apply (with bounds), so preferences, tool habits, and
failure patterns become durable without fine-tuning weights on every
turn or inventing uncontrolled self-modifying agents.

## What Changes

- Introduce capability **`assistant-self-improvement`**: continuous
  learning pipeline for the local assistant (voice + text), layered on
  existing `memory-rag` + `agent-runtime`.
- **First-class Session** (not only a string `session_id`):
  - A session is **open** until farewell / explicit done / idle timeout /
    failed terminal state — while open it owns **short-term memory**
    (turns, pending slots, active job).
  - Example: “查 AMD 股價” → Hermes 結果 → “幫我看其他天” stays in the
    **same** session with prior turns + tool result still in STM.
  - Voice today reuses a fixed id (`voice-assistant`) but does not model
    session *lifecycle*; this change makes lifecycle explicit and API-
    visible (`GET /sessions`, active session on overlay/portal).
- **Three memory horizons** (formalize, not invent from scratch):
  - Short-term: **bound to open session** (turns + pending + last tool
    summary) — cleared only when session completes (after consolidate).
  - Mid-term: session episodes + recent consolidations.
  - Long-term: mem0 facts with **default infer**, mirror to chat lane.
- **Activity notify (real-time progress)**:
  - Unify `task_jobs` progress + `ux_bridge` + desktop notifications into
    an **activity stream** for in-flight sessions/jobs.
  - Surfaces: voice overlay `working` detail, portal “Activity” card,
    `notify-send` (or KDE progress) on phase changes and completion —
    so user sees “Hermes 查 AMD… 60% / 正在讀取頁面” while session is
    still running, not only a final toast.
- **Episode log**: every `/chat` turn writes a structured event
  (session_id, route, worker, user, reply, end_session, latency,
  outcome, optional job_id).
- **Self-critique job** (async, idle/low-load): sample recent episodes,
  extract durable lessons (preferences, tool habits, STT repairs,
  routing few-shots).
- **Routing learning (bounded)**: soft priors / few-shots only; daily
  remains model-judged (no keyword-only daily gate).
- **End-of-conversation policy**: farewell / empty / idle; records
  good vs bad dismiss for later thr proposals (human-approved).
- **Safety envelope**: no automatic weight fine-tune; no silent tool
  grant widen; no off-box upload; no auto-edit of modules/systemd.
- **Observability**: doctor/portal for sessions open, activity queue,
  last infer, self-improve health.

## Capabilities

### New Capabilities

- `assistant-self-improvement`: Continuous on-device improvement loop —
  **session lifecycle + STM**, episode logging, multi-horizon
  internalization, **activity notify**, async critique/consolidation,
  bounded routing priors, and safety constraints. Consumes LiteLLM +
  mem0; extends agent-orchestrator, voice UX, and portal.

### Modified Capabilities

- `agent-runtime`: first-class session registry; `/chat` binds to an
  open session; `end_session` completes it; workers push activity
  progress; daily intent remains model-first.
- `memory-rag`: continuous infer + chat-lane mirror; consolidate on
  session complete (not only arbitrary TTL wipe).

## Impact

- **Modules (primary)**:
  - `modules/agent-orchestrator/` — session registry, episode log,
    internalize, activity API (`/sessions`, `/jobs` progress already
    partial via `task_jobs`), classifier few-shots.
  - `modules/memory-mem0/` — infer timeout / health as needed.
  - `modules/voice-pipecat/` / `voice-wake` / overlay — bind voice to
    open session; show activity; session-end dismiss.
  - `modules/system-aipc-portal/` — Activity card (live sessions +
    progress lines).
  - Optional: `modules/agent-self-improve/` timer for critique.
- **LiteLLM / Lemonade**: extra async NPU/GPU load for infer + critique
  — must be **off critical path** (after TTS, idle, or low priority).
- **Secrets / network**: no new cloud dependency; learning offline once
  weights present.
- **User-visible defaults**: slightly more “remembers you” behaviour;
  dismiss may become smarter over time; **no** silent grant of risky
  tools.
- **Tests**: static + render for units; hardware-verified soak for
  “teach → next session recall” and “stock multi-turn → Hermes”.
