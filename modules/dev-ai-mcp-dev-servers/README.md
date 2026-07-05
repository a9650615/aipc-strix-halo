# dev-ai-mcp-dev-servers

Development MCP servers — Filesystem, GitHub, and Playwright — registered
with the Phase 4 agent-mcp-gateway (when available).

## What it does

- Registers three MCP servers, run on demand via `npx -y` (no global
  install): `@modelcontextprotocol/server-filesystem`,
  `@modelcontextprotocol/server-github`, `@playwright/mcp` (all confirmed
  present on the npm registry 2026-07-06; an earlier draft of this README
  and an earlier `@anthropic-ai/mcp-server-playwright` in servers.json were
  fictitious package names that would 404 on npx — fixed).
- Ships the registration manifest at `/etc/aipc/mcp/servers.json`.

## Status

**Disabled** — blocked on `phase-4-agent` (agent-mcp-gateway not yet specced).
The `.disabled` marker is removed once the gateway module lands.

## Dependencies

- `llm-litellm` (gateway for any model calls from MCP tools).
- `dev-distrobox-templates` (Node template for npm packages).

## Consumers

Phase 4 agent-mcp-gateway reads the manifest to register these servers.
