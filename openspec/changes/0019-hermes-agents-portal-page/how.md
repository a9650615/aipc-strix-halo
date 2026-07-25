# How — hermes-agents-portal-page

## Architecture

```text
Browser  GET /agents  (Astro SPA page)
   │
   ├─ GET /api/v1/agents                  ─┐
   ├─ GET /api/v1/agents/delegations/:id   ├─ aipc-portal (stdlib HTTP)
   ├─ GET /api/v1/agents/kanban/:id        │   agents.py read-only
   └─ GET /api/v1/agents/logs              ─┘
              │
              ├─ ~/.hermes/state.db   (async_delegations)
              ├─ ~/.hermes/kanban.db  (tasks, comments, events)
              ├─ ~/.hermes/logs/*     (agent.log tail)
              └─ /proc + peer bin/auth paths
```

Portal already runs as a system unit (often root). Hermes data lives in the
desktop user's home. Resolve home the same way agent-orchestrator does:
`AIPC_HERMES_HOME` → `AIPC_HERMES_USER`/`AIPC_PRIMARY_USER` → scan
`/var/home/*/.hermes` and `/home/*/.hermes` for `state.db`.

Peer binaries are not always on root's PATH; probe
`~/.local/bin`, `~/.npm-global/bin`, `~/.grok/bin`, and brew prefixes.

## Implementation notes

- SQLite: open read-only URI (`mode=ro`) with short timeout; swallow lock errors.
- Truncate goal/summary previews in list API; full text only on detail.
- Process filter: match argv basenames `claude`, `codex`, `grok`; drop
  `mcp-server`, `mcp-stdio-watchdog`, and continuity hooks noise.
- Static build: `cd modules/system-aipc-portal/web && npm run build`, copy
  `dist/` into `files/usr/lib/aipc-portal/static/`.
- Live hotfix path after hardware check: copy into `/usr/local/lib/aipc-portal/`
  (current machine layout) only when user asks.

## Tests

- Unit: `agents.py` against fixture SQLite + fake process table.
- Server: routes return JSON shape; 404 for unknown id; missing home → empty ok.
- SPA contract: nav link + `/api/v1/agents` usage in `agents.astro`.
