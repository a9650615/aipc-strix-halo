# agent-orchestrator

LangGraph supervisor (D1). Full design dispatches 4 sub-agents (D2):
- Researcher (default: `coder-fast`)
- Coder (default: `coder-strong`)
- Browser (default: `vlm-qwen2vl`)
- Daily Assistant (default: `intent-3b`)

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
  Daily Assistant sub-agent graph, model alias `intent-3b`, three tools
  bound via `ChatLiteLLM.bind_tools()` and dispatched through
  `langgraph.prebuilt.ToolNode`/`tools_condition` (both already ship
  inside the pinned `langgraph==1.2.7` — no new dependency):
  - `calendar_lookup`, `email_lookup` — **stubs**. `agent-tools-calendar`
    (tasks 4.2 Google / 4.3 Proton / 4.4 Fastmail) doesn't exist yet;
    both always return
    `{"status": "not_configured", "tool": "...", "detail": "..."}`
    until one of those backends lands.
  - `files_read` — **stub with an assumed interface contract**. Task 4.1
    (`agent-tools-files`) is being built in parallel in a sibling module
    not present in this working tree. `files_read` tries:
    ```python
    from aipc_agent_tools_files import read_file
    read_file(path: str) -> str   # raises PermissionError if `path` is
                                   # outside the allowlist at
                                   # /etc/aipc/agent-tools/files-allowlist.conf
    ```
    If the import fails (module not installed) it returns the same
    `not_configured` shape as calendar/email. If `read_file` raises
    `PermissionError`, it returns `{"status": "denied", "tool":
    "files.read", "detail": "..."}`. **Whoever implements
    `agent-tools-files` (task 4.1) should either match this signature or
    tell this module's owner so `daily_assistant.py`'s import/call site
    gets updated to match** — this contract was chosen unilaterally to
    unblock 2.6, not negotiated with the 4.1 implementer.
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

**Hardware-verified 2026-07-06** (supervisor-only, pre-2.6): with Ollama
idle, `POST /chat {"text": "say OK"}` against the live service returned
`HTTP 200 {"text":"OK","task_id":"..."}` — the full `/chat` → supervisor
→ LiteLLM → Ollama (`ornith-35b`) round trip works end to end on real
hardware. `.disabled` removed per CLAUDE.md §9.

**Daily Assistant (task 2.6) is static/mocked-verified only, no
hardware access in this session** (CLAUDE.md §9): graph construction,
keyword routing, tool-stub fail-closed shape, and the `intent-3b` model
alias reaching `ChatLiteLLM` are all checked with the LLM call mocked
(`aipc_agent/graphs.py`'s `self_test()`, `python3 -m aipc_agent.graphs
--self-test`). The live `/chat` → supervisor → daily_assistant →
LiteLLM → `intent-3b` round trip has NOT been exercised against real
hardware — do that before treating 2.6 as more than render/mock-verified,
and confirm `intent-3b` is actually registered in
`modules/llm-litellm`'s current model manifest (the same 2026-07-04 trim
that cut `main-70b` may have touched this alias too).

## Dependencies
- llm-litellm (all LLM calls route through the gateway)
- agent-tools-search, agent-browser, agent-code-shell (sub-agent tools —
  not yet wired up)
- agent-tools-files (task 4.1, in progress in parallel): `daily_assistant.py`
  assumes `from aipc_agent_tools_files import read_file` — see the
  `files_read` contract above; reconcile signatures when that module lands.
- agent-tools-calendar (tasks 4.2–4.4, not started): `calendar_lookup`/
  `email_lookup` are stubs until one of its backends exists.

## Spec
openspec/changes/phase-4-agent — tasks 1.1, 2.1, 2.2, 2.6, 7.1–7.3 done
here; 2.3–2.5, 2.7, and groups 3–9 remain.
