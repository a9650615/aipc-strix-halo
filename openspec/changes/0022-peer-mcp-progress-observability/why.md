# Why — peer-mcp-progress-observability

The 0019 Agents page can show Hermes delegations, peer process presence, and
completed log summaries, but a peer MCP call such as `ask_claude` is not a
durable first-class run. The live MCP server keeps only an in-memory PID map
and waits for subprocess completion before returning output. The dashboard
therefore cannot reliably show that a peer was dispatched, how long it has
been running, or what it most recently emitted.

Operators need one small, local progress contract for `ask_claude`,
`ask_codex`, `ask_grok`, and `collaborate` so the dashboard can show live
lifecycle state without parsing each CLI's private token stream.
