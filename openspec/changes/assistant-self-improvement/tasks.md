# tasks: assistant-self-improvement

## 1. Productize live hotfixes (Phase A)

- [x] 1.1 Land `memory.internalize` / `consolidate_session` / chat-lane mirror in module tree (not only `/var/lib` live)
- [x] 1.2 Wire internalize on respond, hermes, daily, coder, screen, stream paths; Hermes skip default **off**
- [x] 1.3 Keep `end_session` + voice-once exit `2` + wake `session-end` dismiss; document in agent README
- [x] 1.4 Episode JSONL writer middleware on `/chat` (+ stream done event)
- [x] 1.5 Health surface: `/healthz.sessions_open` + portal `agent-activity` yaml + episodes dir
- [x] 1.6 Static tests: internalize worth-filter, end_session farewell, no daily keyword-only gate in classifier rules
- [x] 1.7 Hardware: multi-turn stock session + farewell done; mem0 preference facts present

## 1b. Session registry + STM binding (Phase A+)

- [x] 1b.1 `SessionRegistry` (create / resume / complete / fail) with status enum
- [x] 1b.2 Voice always passes stable open session id (resume until done)
- [x] 1b.3 STM (`agent_context`) keyed only by open session; clear on complete after consolidate
- [ ] 1b.4 Pending slots (stock/coding) stored on session object
- [x] 1b.5 Hardware: AMD 股價 → 結果 →「其他天」same session uses prior context

## 1c. Activity notify (Phase A+)

- [x] 1c.1 Activity bus: session.last_activity + optional progress_pct from task_jobs
- [x] 1c.2 Overlay shows live line while `working` (reuse ux_bridge)
- [x] 1c.3 Throttled desktop notify on phase change + completion notify
- [x] 1c.4 Portal service registration (`agent-activity.yaml` → `/activity`)
- [x] 1c.5 API: `GET /sessions`, `GET /sessions/{id}` 
- [x] 1c.6 Hardware: Hermes run shows progress on overlay/portal before final TTS

## 2. Critique + routing priors (Phase B)

- [ ] 2.1 Add `aipc-self-improve.timer` + oneshot (idle/night) reading episodes
- [ ] 2.2 Critique prompt → JSON lessons; write mem0 + `/var/lib/aipc-agent/learning/fewshots.json`
- [ ] 2.3 Intent classifier injects few-shots into system prompt (cap N, LRU)
- [ ] 2.4 STT repair map auto-apply only for high-confidence pairs (reversible file)
- [ ] 2.5 Safety ledger for rejected auto-applies
- [ ] 2.6 Hardware: correct “要用 Hermes 查股” thrice → later “查 AMD” routes hermes without re-teaching

## 3. Eval + dismiss learning (Phase C)

- [ ] 3.1 Offline replay harness: episode fixtures → expected target / end_session
- [ ] 3.2 Metrics: misroute rate, empty follow-up rate, recall hit rate (session log)
- [ ] 3.3 Dismiss proposals (thr/silence) as markdown only — no auto unit edit
- [ ] 3.4 Render-verify bootc + ansible for any new module/timer units

## 4. Optional LoRA lab (Phase D — separate approval)

- [ ] 4.1 Design only: scratch adapter path, never default production alias
- [ ] 4.2 Require explicit user opt-in + OpenSpec archive before any weight train job

## 5. Docs

- [ ] 5.1 Update `modules/agent-orchestrator/README.md` + `memory-mem0` with self-improve diagram
- [ ] 5.2 `docs/agent-log.md` row when Phase A lands on hardware
- [ ] 5.3 User-facing note: learning is on-box, async, not “instant cloud memory”
