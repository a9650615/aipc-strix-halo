## Why

Phases 0–1 stood up the OS image and the LLM gateway; Phase 6 ships the
developer surface. Phase 4 is the layer that turns the LLM gateway into
*agents*: long-lived sub-agents that take goals, plan, call tools, and act
on the user's machine — including code execution, browser automation, and
screen control.

The architecture decision is a multi-agent supervisor topology built on
LangGraph, with four sub-agents shipped on day one (Researcher, Coder,
Browser, Daily Assistant). Every agent loop addresses models by alias
through the Phase 1 LiteLLM gateway, every code action runs inside a
sandboxed distrobox, and every risky action (delete, push, install, send,
spend) goes through a single permission gate. Browser automation is
Playwright MCP and the MCP registry is a shared config file — not another
daemon — so Phase 6's dev tools and Phase 4's sub-agents see the same set
of MCP servers.

## What Changes

- **New capability `agent-runtime`** covering the 8 Phase 4 modules as one
  coherent host-side agent surface.
- **LangGraph as the single agent framework**: supervisor graph + four
  sub-agent graphs (Researcher, Coder, Browser, Daily Assistant), state
  checkpointed to sqlite so a crash or reboot allows manual `aipc agent
  resume <id>`.
- **Per-sub-agent model defaults via LiteLLM aliases**: supervisor uses
  `main-70b`; Researcher uses `coder-fast` (or `main-70b` for hard
  questions); Coder uses `coder-strong`; Browser uses `vlm-qwen2vl`;
  Daily Assistant uses `intent-3b`.
- **Sandboxed code execution**: Open Interpreter runs inside a new
  distrobox container `agent-runtime` (parallel to Phase 6's Node/Python
  dev distroboxes); the host filesystem is not directly writable from
  agent shell actions.
- **Browser sub-agent uses Playwright MCP**, not browser-use. The
  Playwright MCP server is registered with the shared MCP registry so
  Phase 6 dev tools and the Phase 4 Browser sub-agent share one browser
  backend.
- **Screen control ships in two modes**: session-gate (default — user
  grants "next 30 min the agent can control the screen") and always-on
  with explicit window-class blacklist (opt-in). The Qwen2-VL VLM
  inspects the screen; xdotool/ydotool drive input.
- **Risky-action permission gate**: a single daemon `aipc-agent-gate`
  brokers grants for file-delete-outside-workspace, git-push, package
  install, email-send, and cloud-API spend. Grants are scoped per session
  (with timeout) or per task loop (auto-revoked when the supervisor
  reports the task done).
- **Tool suite**: filesystem (allowlisted paths only), calendar + email
  via Google OAuth and Proton/Fastmail IMAP/CalDAV, search via SearXNG
  self-host (default) with Tavily API as an opt-in upgrade.
- **MCP registry is a shared config file**, not a daemon:
  `/etc/aipc/mcp/servers.json` is read by every MCP-aware client
  (Phase 6 dev tools and Phase 4 sub-agents). MCP servers themselves run
  as independent processes per the MCP spec.
- **Voice → agent interface**: HTTP POST `/chat` on the orchestrator
  daemon; Phase 3 Pipecat converts voice to text and POSTs.

## Capabilities

### New Capabilities

- `agent-runtime`: Host-side agent surface — LangGraph orchestrator with
  one supervisor + four sub-agent graphs, sandboxed code execution, MCP
  registry config, permission gate for screen control and risky actions,
  and the tool modules (files, calendar/email, search, browser, screen).
  Every LLM call routes through the Phase 1 LiteLLM gateway.

### Modified Capabilities

- `ai-runtime` (Phase 1): No requirement changes. Phase 4 is a downstream
  consumer of the LiteLLM gateway contract from CLAUDE.md §7.

## Impact

- **`modules/`**: 8 new modules added (see tasks group 1). No existing
  module is touched.
- **`tools/aipc doctor`**: Gains an `agent-runtime` section — LangGraph
  importable, sandbox container exists, SearXNG quadlet active, MCP
  registry parseable, permission-gate service active.
- **`targets/bootc/Containerfile` + `targets/ansible/site.yml`**:
  Rendered outputs grow by 8 modules; both targets must reach the same
  end state.
- **Downstream consumers**: Phase 3 (voice) posts to `/chat`; Phase 6
  dev tools share the MCP registry.
- **Phase 6 dependency**: `agent-mcp-gateway`'s registry schema must
  match what `dev-ai-mcp-dev-servers` writes. The Phase 6 spec already
  defers its registration step to whatever Phase 4 declares — this
  change is the answer (Open Question Q1 in `phase-6-dev/design.md`).
- **Phase 3 dependency**: The voice contract is HTTP POST `/chat` with
  text bodies; Pipecat is the only producer. Pipecat itself is shipped
  by Phase 3 and is out of scope here.
- **Phase 7 dependency (deferred)**: Long-running background tasks (run
  while the user does other things, with notifications) are deferred to
  Phase 7 ops — Phase 4 ships inline tasks with LangGraph checkpoint
  resume only.
