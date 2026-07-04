# agent-orchestrator

LangGraph supervisor (D1). Full design dispatches 4 sub-agents (D2):
- Researcher (default: `coder-fast`)
- Coder (default: `coder-strong`)
- Browser (default: `vlm-qwen2vl`)
- Daily Assistant (default: `intent-3b`)

## Current status: basic skeleton only, still `.disabled`

Implemented (tasks 1.1, 2.1, 2.2, 7.1–7.3):
- `files/usr/lib/aipc-agent/aipc_agent/graphs.py`: `supervisor()` — a
  single-node LangGraph graph that answers directly via the LiteLLM
  gateway, model alias `main-70b` (the spec's supervisor default). No
  sub-agent dispatch yet — `researcher`/`coder`/`browser`/`daily_assistant`
  don't exist.
- `files/usr/lib/aipc-agent/aipc_agent/server.py`: FastAPI `POST /chat`
  accepting `{text, session_id?}`, returning `{text, task_id}` on success
  or `{error: {code, message}}` with a non-200 status on failure.
- `files/usr/lib/aipc-agent/requirements.txt`: pinned versions
  (`langgraph==1.2.7`, `langchain-litellm==0.6.4`, `fastapi==0.139.0`,
  `uvicorn==0.50.0`, `aiosqlite==0.22.1` — task 2.1).
- `post-install.sh` builds a venv at `/usr/lib/aipc-agent/venv`, installs
  the pinned requirements, enables `aipc-agent-orchestrator.service`.
- `files/etc/systemd/system/aipc-agent-orchestrator.service`: native
  systemd unit (not a container/quadlet — this daemon doesn't need
  sandboxing, only the future Coder sub-agent's code execution does),
  binds `127.0.0.1:4100` per `env/endpoint`.

Not implemented yet (deferred, matches tasks 2.3–2.6 / groups 3/4/5/6):
sub-agent dispatch, tool suite, permission gate, `agent-runtime` sandbox
distrobox, MCP registry, LangGraph sqlite checkpointer/resume.

**Verified 2026-07-04**: `ChatLiteLLM(model=..., api_base="http://127.0.0.1:4000",
custom_llm_provider="openai", api_key="aipc-local")` round-trips a real chat
completion against the live LiteLLM gateway (tested against `resident-small`).
The `supervisor` graph and the `/chat` endpoint's happy/error paths are
verified with the LLM call mocked (state flows through correctly, model
alias `main-70b` is what gets called, error path returns the documented
`502`/`error.code` shape). Live end-to-end verification of the full
`/chat` → supervisor → LiteLLM → Ollama round trip on `main-70b` itself is
**not yet done** — Ollama was continuously busy with unrelated large
background jobs (apparent mem0 session-summarization traffic) every time
this was attempted; re-run once Ollama has an idle window. Module stays
`.disabled` until that's done, per CLAUDE.md §9 (only a hardware-verified
claim moves a module out of `.disabled`).

## Dependencies
- llm-litellm (all LLM calls route through the gateway)
- agent-tools-search, agent-browser, agent-code-shell, agent-tools-files, agent-tools-calendar (sub-agent tools — not yet wired up)

## Spec
openspec/changes/phase-4-agent — tasks 1.1, 2.1, 2.2, 7.1–7.3 done here; 2.3–2.7 and groups 3–9 remain.
