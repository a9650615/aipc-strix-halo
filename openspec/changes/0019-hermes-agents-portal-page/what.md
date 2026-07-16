# What — hermes-agents-portal-page

## Scope (v1)

### system-aipc-portal backend

New read-only aggregator module `aipc_portal/agents.py` that resolves the
primary Hermes home (`AIPC_HERMES_HOME` / `AIPC_PRIMARY_USER` / first
`{user}/.hermes` with `state.db`) and exposes:

| Endpoint | Returns |
|---|---|
| `GET /api/v1/agents` | Snapshot: peer CLI readiness, live peer processes, Hermes `async_delegations`, kanban tasks, summary counts |
| `GET /api/v1/agents/delegations/{id}` | One delegation: goal, state, model, duration, tool_trace, result summary, log tail |
| `GET /api/v1/agents/kanban/{id}` | One kanban task: body, comments, recent events, workspace/branch/pid |
| `GET /api/v1/agents/logs?q=&limit=` | Tail of `~/.hermes/logs/agent.log` (and optional `errors.log`), filter substring |

Missing Hermes home or unreadable DBs return structured empty lists +
`availability: unavailable` — never 500 for "not provisioned yet".

### system-aipc-portal SPA

- New page `web/src/pages/agents.astro` at `/agents` (same pattern as Memory).
- Nav link in `App.astro`: **Agents**.
- UI: peer status chips, live process cards, dual lists (Delegations / Kanban)
  with status pills, master-detail log panel, auto-refresh ~5s.
- Rebuild `web/dist/` → `files/usr/lib/aipc-portal/static/`.

### Data sources (v1)

1. `~/.hermes/state.db` → `async_delegations`
2. `~/.hermes/kanban.db` → `tasks` (+ comments/events on detail)
3. Process table scan for `claude` / `codex` / `grok` agent turns (best-effort;
   excludes idle `mcp-server` helpers when possible)
4. Peer install/auth probe (which + auth file presence; no slow auth CLI on every poll)
5. `~/.hermes/logs/agent.log` tail for log panel

## Out of scope

- Voice orchestrator `/jobs` (explicitly deferred; Home Automation strip stays).
- Cancelling / killing peer processes from the UI.
- Auth / remote access (stays loopback).
- Writing into Hermes DBs or replacing hermes-webui.
- Packaging peer-agents MCP itself.
