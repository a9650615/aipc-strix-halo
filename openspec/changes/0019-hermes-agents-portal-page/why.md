# Why — hermes-agents-portal-page

Hermes dispatches long-running background work — native `async_delegations`,
kanban workers, and subscription peer CLIs (Claude Code / Codex / Grok via
`peer-agents` MCP). Today those runs are visible only by digging into
`~/.hermes/state.db`, `kanban.db`, process lists, and `logs/agent.log`, or by
opening hermes-webui's chat-centric UI.

Control Center already has a status Home and a dedicated Memory page. Operators
need the same kind of dedicated, good-looking surface for **agent fleet
observability**: who is running, what they were asked to do, and recent logs —
without leaving the portal or learning Hermes' internal stores.
