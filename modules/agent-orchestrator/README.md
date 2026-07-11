# agent-orchestrator

LangGraph supervisor (D1). Full design dispatches 4 sub-agents (D2):
- Researcher (default: `coder-fast`)
- Coder (default: `coder-strong`)
- Browser (default: `vlm-qwen2vl`)
- Daily Assistant (default: `intent-3b` per spec; `ornith-35b` in
  practice, see below)

## Closed loop (voice product)

`POST /chat` is the **think** step of the always-on voice closed loop
(SenseVoice → here → Kokoro + mem0). Standing default model is
**`resident-small`** (NPU / Lemonade FLM via LiteLLM), so the loop does not
depend on heavy Vulkan agent models. Override with env
`AIPC_SUPERVISOR_MODEL` (e.g. after `aipc models use agent`). See
`docs/voice-pipeline.md`.

`GET /healthz` is for portal/doctor/loop probes (liveness + `sessions_open`).

### Sessions, activity, internalization (productized)

- **Session registry** (`session_registry.py`): open conversation with
  status `active|working|waiting_user|done|failed`. Short-term memory
  (`agent_context`) stays for the open session so multi-turn tool use
  (e.g. 查 AMD 股價 → 那昨天呢) keeps context. Farewell / `end_session`
  consolidates into mem0 then clears STM.
- **Activity** (`activity.py` + `task_jobs`): live progress for long
  workers → overlay (`ux_bridge`), throttled desktop notify, and
  `GET /activity` + `GET /sessions`. Completing a job leaves the session
  `active` for follow-ups unless the user ends the session.
- **Internalize** (`memory.internalize`): every successful turn enqueues
  async mem0 `infer=true` (chat-lane mirror for tool agents). Does not
  block TTS.
- **Episodes**: JSONL under `/var/lib/aipc-agent/episodes/` (ON by default).
- **Skill tree (two layers):**
  1. **Process teaching** (in aipc image, read-only):
     `/usr/share/aipc-agent/skills-process/` — high-level **tool-use**
     procedures only (how to search/browse/evidence). Maintained in
     this module under `files/usr/share/aipc-agent/skills-process/`.
  2. **Machine growth** (writable): `/var/lib/aipc-agent/skills/`,
     `~/.hermes/skills/aipc-learned/` — path-harvest after *her*
     grounded successes (hosts/URL patterns). Never commit answer
     corpora into `modules/**`.
  **Supervisor rule:** do not seed titles/cast/site answers into either
  layer. Process skills may teach tools; machine skills accumulate PATH.
- **Sandbox browser (default ON):** Hermes turns equip `-t browser` with
  profile under `/var/lib/aipc-agent/browser-sandbox`
  (`AIPC_HERMES_BROWSER=auto`). Chromium starts only if tools are called.
  Not topic/keyword gated. Pure greet stays on `respond`.
- **Local autonomy + technical advice:** Hermes runs with `--yolo` and
  auto-approved hooks. Code blocks, error lines, and configuration fragments
  are sent to the local `ornith-35b` advisor as a neutral technical subtask;
  Hermes retains the original conversation and remains the final responder.
- **Background learning (default ON):** `AIPC_SKILL_LEARN=1`,
  `AIPC_LEARN_BG=1`, mentor `ornith-35b` / fallback `assistant-gemma`.
  Hermes success turns attach a **tool/URL trail** into the async learn
  queue (never blocks TTS). Idle batch: **`aipc-self-improve.timer`
  enabled by post-install** → episodes → local skills.
  Drop-in: `zzz-skill-learn.conf`. Manual:
  `python -m aipc_agent self-improve --hours 72`.
  See OpenSpec `assistant-self-improvement`.
- **Grounding (anti-invent):** product-style codes (`ABC-123`) force
  Hermes/tools. Skill learn / Hermes ok require a **non-homepage URL**
  in trail or reply. Chat invents (fake cast/title + store root only)
  are rejected and not internalized/learned. See `grounding.py`.
- **Hermes notify + feedback:** completion notify keeps longer text
  (sentence-aware clip, default ~480 chars) and appends
  「不对？下句说『不对』可反馈」. Negative feedback (`不对` / `乱答` / …)
  records an episode, marks recent path skill as unreliable, does not
  treat the prior answer as truth. Optional Hermes TTS
  (`AIPC_HERMES_TTS=1`, default on) speaks a short compress of the reply
  via user-session CosyVoice/Kokoro — **skipped** when the client owns
  TTS (`voice-*` / `krunner` session_id) so voice-once and krunner do not
  double-play (audio overlap).
- **Multi-engine search (default ON):** Hermes may inject hits from
  SearXNG / DDG / Brave / Bing (`AIPC_WEB_HINT_HERMES=auto`). Process
  code has **no per-site catalog hardcodes** — site-specific paths only
  in local skills after a successful learn.
- **Self-learn PATH harvest (default ON):** side paths are allowed at
  runtime (any useful result site). After a **grounded** Hermes success,
  `path_skill_from_evidence` **merges** new hosts/URL patterns into the
  local skill `web-lookup-path` (no supervisor answers; mentor optional).
  Next similar query injects the accumulated skill tree — shorter path
  without hardcoding sites in process.
- **Classifier**: daily intents are **model-judged**
  (`AIPC_CLASSIFIER=always`); stock/live price multi-turn routes to
  Hermes tool path, not “没有工具” chat.

Voice clients should pass a stable `session_id` (default
`voice-assistant`) and treat `end_session: true` as session complete
(wake: no follow-up arm).

## Current status: basic skeleton + Daily Assistant sub-agent, enabled

Implemented (tasks 1.1, 2.1, 2.2, 2.6, 7.1–7.3):
- `files/usr/lib/aipc-agent/aipc_agent/graphs.py`: `supervisor()` answers
  directly via LiteLLM. **Default model: `resident-small`** (closed loop;
  was `ornith-35b` until 2026-07-10). Daily Assistant still uses
  `ornith-35b` for tool-calling. Keyword route to Daily Assistant:
  `calendar`, `schedule`, `meeting`, `email`, `inbox`, `mail`, `file`,
  `read` — **not** remember/memory (those stay on supervisor + mem0).
  This is a simple keyword route, not the generic multi-agent router the
  full spec eventually wants — that waits until Researcher/Coder/Browser
  (2.3–2.5) exist too and a real decomposition step is worth the complexity.
- `files/usr/lib/aipc-agent/aipc_agent/daily_assistant.py` (task 2.6): the
  Daily Assistant sub-agent graph, model alias `ornith-35b`. Spec default
  `intent-3b` doesn't exist post-trim; the next candidate, `resident-small`
  (Lemonade's FastFlowLM NPU backend), was hardware-verified 2026-07-06 to
  reject any request carrying a `tools` list outright (`[json.exception
  .type_error.302] type must be string, but is object` from `llama-server`
  — an NPU-backend limitation, not a request bug: the identical payload
  against `ornith-35b` returns a proper `tool_calls` response). Since
  Daily Assistant needs tool calling to do anything, it reuses the
  supervisor's own `ornith-35b` until a small tool-calling-capable NPU
  model exists. Three tools
  bound via `ChatLiteLLM.bind_tools()` and dispatched through
  `langgraph.prebuilt.ToolNode`/`tools_condition` (both already ship
  inside the pinned `langgraph==1.2.7` — no new dependency):
  - `calendar_lookup`, `email_lookup` — **stubs**. `agent-tools-calendar`
    (tasks 4.2 Google / 4.3 Proton / 4.4 Fastmail) doesn't exist yet;
    both always return
    `{"status": "not_configured", "tool": "...", "detail": "..."}`
    until one of those backends lands.
  - `files_read` — uses `agent-tools-files` (task 4.1) when that sibling
    module is rendered. `post-install.sh` exposes `/usr/lib/aipc-agent` to
    the venv, so `from aipc_agent_tools_files import read_file` works
    without copying code or adding a dependency. If the module is absent,
    the existing `ImportError` fallback still returns `not_configured`;
    outside-allowlist reads return `denied`.
- `files/usr/lib/aipc-agent/aipc_agent/memory.py`: tiny optional mem0 HTTP
  client. It tries loopback mem0 search/add routes with a 1s timeout,
  injects remembered facts into both supervisor and Daily Assistant prompts,
  and fails soft when mem0 is disabled or its route shape changes.
- `files/usr/lib/aipc-agent/aipc_agent/server.py`: FastAPI `POST /chat`
  accepting `{text, session_id?}`, returning `{text, task_id}` on success
  or `{error: {code, message}}` with a non-200 status on failure.
- `files/usr/lib/aipc-agent/requirements.txt`: pinned versions
  (`langgraph==1.2.7`, `langchain-litellm==0.6.4`, `fastapi==0.139.0`,
  `uvicorn==0.50.0`, `aiosqlite==0.22.1` — task 2.1). No new pins added
  for 2.6 — `langchain_core` (tools, messages) ships transitively with
  `langgraph`/`langchain-litellm`.
- `post-install.sh` builds a venv at `/usr/lib/aipc-agent/venv`, installs
  the pinned requirements, exposes `/usr/lib/aipc-agent` via a `.pth` file
  so sibling stdlib packages such as `aipc_agent_tools_files` are importable,
  and enables `aipc-agent-orchestrator.service`.
- `files/etc/systemd/system/aipc-agent-orchestrator.service`: native
  systemd unit (not a container/quadlet — this daemon doesn't need
  sandboxing, only the future Coder sub-agent's code execution does),
  binds `127.0.0.1:4100` per `env/endpoint`.

Not implemented yet (deferred, matches tasks 2.3–2.5, 2.7 / groups 3/4/5/6):
Researcher/Coder/Browser sub-agents, permission gate, `agent-runtime`
sandbox distrobox, MCP registry, LangGraph sqlite checkpointer/resume,
real calendar/email/files backends.

**Hardware-verified 2026-07-06** (full round trip, supervisor + Daily
Assistant): live-hotfixed onto the running service
(`/var/lib/aipc-agent`, see `docs/live-hotfix-workflow.md`) and iterated
until real bugs stopped surfacing:

1. `POST /chat {"text": "say OK"}` (plain, supervisor path) → `HTTP 200
   {"text":"OK",...}` — confirmed `.disabled` could come off per CLAUDE.md
   §9.
2. First `/chat` call with a calendar keyword hit `Invalid model name ...
   intent-3b` — `GET /v1/models` confirmed it's gone (qwen2.5 family cut
   in the 2026-07-04 trim, same as `main-70b`). Tried `resident-small`
   next; it 500'd on any request carrying `tools` (NPU/FastFlowLM backend
   can't do function calling — see above). Settled on `ornith-35b`.
3. With `ornith-35b`, the tool-call turn still failed:
   `litellm.BadRequestError: ... unsupported content[].type`. Root cause
   (confirmed via a standalone `ChatLiteLLM.bind_tools()` repro against
   the live venv): `ornith-35b` returns `content` as
   `[{"type": "thinking", ...}]`, not a string; LangGraph keeps that raw
   `AIMessage` in `messages` state, and resending it verbatim on the next
   tool-loop turn is what `llama-server` rejects. The existing `_text_of`
   helper in `graphs.py` only normalized the supervisor's *final* answer,
   not messages flowing through a tool loop. Fix: extracted the helper to
   `aipc_agent/_util.py` (`text_of`), and now `daily_assistant.py` applies
   it to every `AIMessage` before it re-enters state (`_agent`) and to the
   final answer (`_finish`).
4. Also recovered two real fixes (`max_tokens=2048` cap on the
   supervisor's `ChatLiteLLM` call, plus what's now `text_of`'s original
   form) that existed live on this machine (hardware-verified
   2026-07-04/05) but were never committed — a prior session's
   live-hotfix-workflow.md step 5 ("commit the repo file") was skipped;
   folded back in here so they survive the next `bootc switch`.

Final verification, all green: `python3 -m aipc_agent.graphs --self-test`
passes against the real venv; `POST /chat {"text": "what is on my
calendar today"}` → routes to `daily_assistant` → `ornith-35b` calls
`calendar_lookup` → coherent natural-language reply, `HTTP 200`; same for
an email-keyword query; plain-text regression (`"reply with exactly:
pong"` → `{"text": "pong", ...}`) confirms the supervisor path is
unaffected.

## Dependencies
- llm-litellm (all LLM calls route through the gateway)
- agent-tools-search, agent-browser, agent-code-shell (sub-agent tools —
  not yet wired up)
- agent-tools-files (task 4.1): `daily_assistant.py`'s `files_read` imports
  `aipc_agent_tools_files`; post-install's `.pth` makes the sibling package
  visible when it is present, and the tool fails closed when it is absent.
- memory-mem0 (optional, Phase 2): consumed over HTTP only; disabled or
  unreachable mem0 never breaks `/chat`.
- agent-tools-calendar (tasks 4.2–4.4, not started): `calendar_lookup`/
  `email_lookup` are stubs until one of its backends exists.

## Spec
openspec/changes/phase-4-agent — tasks 1.1, 2.1, 2.2, 2.6, 7.1–7.3 done
here; 2.3–2.5, 2.7, and groups 3–9 remain.
