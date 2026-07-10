# design: assistant-self-improvement

## Decision

Ship a **four-loop self-improvement system** that never fine-tunes
production weights on the fly. Learning is:

1. **Episodic** (what happened)
2. **Semantic** (what is true about the user / world for this PC)
3. **Procedural priors** (how we should route / dismiss next time)
4. **Evaluation** (did the prior help?)

All four stay **on-box**, async to the voice critical path
(STT → plan → reply → TTS).

### Architecture (target)

```
  wake / PTT / portal ──► SessionRegistry.open_or_resume()
                              │  id, status, stm_turns, pending, job_id
                              ▼
  /chat {session_id} ──► plan → worker ──┬── short reply
                              │          └── long job (Hermes…)
                              │                 │
                              │                 ▼
                              │          ActivityBus.publish(progress)
                              │                 │
                              │    ┌────────────┼────────────┐
                              │    ▼            ▼            ▼
                              │ overlay     portal card   notify-send
                              │ (working)   (Activity)    (phase/done)
                              │
                              ▼
                    agent_context[session]  (STM while status≠done)
                              │
                    memory.internalize() ──async──► mem0
                              │
              session complete (end_session / idle / job terminal)
                              ▼
                    consolidate_session() → clear STM
                              │
         idle timer           ▼
                    aipc-self-improve (critique → few-shots / ledger)
```

### Session model

A **Session** is the unit of unfinished work the user can still talk to:

```json
{
  "id": "voice-20260710-t3f9",
  "status": "active|working|waiting_user|done|failed",
  "title": "查 AMD 股價",
  "created_ts": 0,
  "updated_ts": 0,
  "source": "voice|portal|api",
  "job_id": null,
  "pending": null,
  "last_activity": "Hermes 讀取報價頁…",
  "progress_pct": null
}
```

| Status | Meaning | STM | Activity UI |
|--------|---------|-----|-------------|
| `active` | multi-turn chat open, mic follow-up ok | kept | overlay followup |
| `working` | Hermes/daily long job running | kept | live progress |
| `waiting_user` | slot-fill (哪支股票？) | kept | overlay recording/followup |
| `done` | farewell / idle / explicit end | cleared after consolidate | hide |
| `failed` | hard error terminal | optional keep 1 retry | error notify |

**Voice binding:** wake opens or resumes **one foreground session**
(default). Follow-up turns must use the same `session_id` (not a new
UUID per `/chat`). Today `voice-assistant` is a constant string without
status — replace with registry-backed ids (constant *namespace* ok, but
lifecycle fields required).

**Example continuum**

1. User: 用 Hermes 查 AMD 股價 → session `working` + job_id  
2. Activity: “啟動 Hermes” → “瀏覽報價” → overlay/portal/notify  
3. Reply spoken; session → `active` (STM has Q+A)  
4. User: 幫我看昨天 / 其他天 → same session STM + Hermes again  
5. User: 没事了 → `done`, consolidate, clear STM, hide activity  

### Activity notify

Unify three existing half-channels:

| Channel | Today | Target |
|---------|--------|--------|
| Overlay | `ux_bridge.progress` → `working` | bind to `session_id` + progress line |
| Desktop | `task_jobs` notify-send on **finish** only | also **phase** updates (throttled) |
| Portal | little/no live job UI | **Activity** card: list open sessions + last_progress |
| API | `GET /jobs`, `GET /jobs/{id}` | + `GET /sessions`, `GET /sessions/{id}` (incl. progress) |

Rules:

- Throttle desktop phase notifies (e.g. ≥8s or phase label change) to
  avoid spam.
- Overlay always shows latest line while session `working`.
- Completing a job does **not** end the session unless `end_session` or
  no follow-up policy says so — user may still ask “其他天”.

### Layers

| Layer | Store | Lifetime | Writer | Reader |
|-------|--------|----------|--------|--------|
| Session | registry file/RAM under `/var/lib/aipc-agent/sessions/` | until done + grace | orchestrator, wake | voice, portal, doctor |
| Short-term | `agent_context` keyed by session id | **while session open** | all workers | respond / slot-fill / consolidate |
| Activity | job progress ring + session.last_activity | while working | task_jobs / hermes | overlay, portal, notify |
| Episode | JSONL | days–weeks | middleware | critique, eval |
| Long-term | mem0 | durable | internalize / consolidate | recall |
| Routing priors | few-shot bank | durable | critique | classifier |
| Safety ledger | append-only | durable | auto-apply refusals | human |

### Critical path rules

- Voice first token / TTS **must not wait** for infer or critique.
- `recall` stays short wall (≤ ~1.5s voice); miss → empty, never hang.
- `infer` / consolidate use **long wall** (60–120s) and **always async**.
- Classifier remains **model-first for daily**; self-improve may only
  inject **few-shot examples**, not resurrect keyword-only daily gates.

### Self-critique job (phase B)

Input: last K episodes (default 50) + existing mem0 top facts.  
Output JSON:

```json
{
  "preferences": ["user prefers concise Chinese"],
  "tool_habits": ["stock price → hermes"],
  "stt_repairs": [{"from": "顾家", "to": "股价"}],
  "dismiss_notes": ["do not end follow-up on incomplete progressive"],
  "routing_fewshots": [
    {"user": "查一下 AMD", "target": "hermes", "mode": "short"}
  ]
}
```

Apply policy:

| Field | Auto-apply? |
|-------|-------------|
| preferences → mem0 | yes (infer already) |
| tool_habits → mem0 + few-shot | yes if score ≥ threshold and consistent ≥ 3 times |
| stt_repairs → transcript_repair map | yes only for high-confidence, reversible map file |
| dismiss_notes | **no** — open OpenSpec / user confirm for thr changes |
| routing_fewshots | yes, max N entries, LRU, never override explicit oneshot |

### What we explicitly will not do (v1)

- Online LoRA / full fine-tune of gemma/ornith without a separate change.
- Auto-edit of `modules/**` or systemd units without grant.
- Cross-user memory bleed (single primary user id stays the scope).
- Cloud upload of episodes.

### Phasing

| Phase | Deliverable | Hardware bar |
|-------|-------------|--------------|
| **A** | Formalize internalize + episode log + consolidate on end + doctor | teach preference → next session recall |
| **B** | Timer critique job + few-shot bank for classifier | stock multi-turn + corrected route sticks |
| **C** | Eval harness (offline replay of episodes) + thr proposal only | report before/after misroute rate |
| **D** (optional) | Opt-in LoRA lab path for a *scratch* adapter, never default | separate OpenSpec |

### Alternatives considered

1. **Only mem0 raw transcripts** — rejected; no “internalization”, noise.
2. **Always retrain classifier weights** — rejected; heavy, unsafe default.
3. **Full agent self-edit of repo** — rejected for v1; violates module discipline.
4. **Keyword growth for daily** — rejected (user: daily must be model-judged).

### Live state already partially aligned (as of 2026-07-10)

- `memory.internalize` / consolidate hooks on respond; Hermes skip default off.
- `end_session` + wake exit 2 for farewell dismiss.
- Intent classifier `AIPC_CLASSIFIER=always`, daily keyword rules removed.
- Stock multi-turn slot → Hermes works hardware-side.

This change **productizes** those hotfixes into a named capability with
specs, timer job, episode log, and eval — so they survive image rebuild
and review.
