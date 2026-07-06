# agent-orchestrator

LangGraph supervisor (D1). Full design dispatches 4 sub-agents (D2):
- Researcher (default: `coder-fast`)
- Coder (default: `coder-strong`)
- Browser (default: `vlm-qwen2vl`)
- Daily Assistant (default: `intent-3b` per spec; `ornith-35b` in
  practice, see below)

## Current status: basic skeleton + Daily Assistant sub-agent, enabled

Implemented (tasks 1.1, 2.1, 2.2, 2.6, 7.1–7.3):
- `files/usr/lib/aipc-agent/aipc_agent/graphs.py`: `supervisor()` answers
  directly via LiteLLM (model alias `ornith-35b` — `main-70b`, the spec's
  original supervisor default, was cut from the manifest in a 2026-07-04
  trim; `ornith-35b`, a 35B reasoning + agentic-coding model, is the
  closest remaining fit), OR routes to the Daily Assistant sub-graph on an
  explicit keyword match (`calendar`, `schedule`, `meeting`, `email`,
  `inbox`, `mail`). This is a simple keyword route, not the generic
  multi-agent router the full spec eventually wants — that waits until
  Researcher/Coder/Browser (2.3–2.5) exist too and a real decomposition
  step is worth the complexity.
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
  - `files_read` — **stub**. `agent-tools-files` (task 4.1) landed as a
    sibling module (`modules/agent-tools-files/`) with a real
    `read_file(path: str) -> str` (raises `AllowlistViolation`, a
    `PermissionError` subclass, outside the allowlist) — matches the
    interface `daily_assistant.py` assumed almost exactly. It isn't wired
    into agent-orchestrator's venv yet (not in `requirements.txt`/
    `post-install.sh`), so the `ImportError` fallback still fires and
    returns the same `not_configured` shape as calendar/email. Wiring the
    two together (add the dependency, drop the `ImportError` branch) is
    follow-up work, not done here.
- `files/usr/lib/aipc-agent/aipc_agent/server.py`: FastAPI `POST /chat`
  accepting `{text, session_id?}`, returning `{text, task_id}` on success
  or `{error: {code, message}}` with a non-200 status on failure.
- `files/usr/lib/aipc-agent/requirements.txt`: pinned versions
  (`langgraph==1.2.7`, `langchain-litellm==0.6.4`, `fastapi==0.139.0`,
  `uvicorn==0.50.0`, `aiosqlite==0.22.1` — task 2.1). No new pins added
  for 2.6 — `langchain_core` (tools, messages) ships transitively with
  `langgraph`/`langchain-litellm`.
- `post-install.sh` builds a venv at `/usr/lib/aipc-agent/venv`, installs
  the pinned requirements, enables `aipc-agent-orchestrator.service`.
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
- agent-tools-files (task 4.1, landed as `modules/agent-tools-files/` but
  not yet in this module's `requirements.txt`/`post-install.sh`):
  `daily_assistant.py`'s `files_read` imports `aipc_agent_tools_files`;
  wiring it in is follow-up work.
- agent-tools-calendar (tasks 4.2–4.4, not started): `calendar_lookup`/
  `email_lookup` are stubs until one of its backends exists.

## Spec
openspec/changes/phase-4-agent — tasks 1.1, 2.1, 2.2, 2.6, 7.1–7.3 done
here; 2.3–2.5, 2.7, and groups 3–9 remain.
