# What

## memory-mem0

- `GET /memories` — list stored memories; optional `user_id` / `agent_id` /
  `run_id` / `app_id` / `limit` query params, all ANDed as a flat filters
  dict. No scope params = list everything (management-UI semantics).
- `DELETE /memories/{id}` — delete one memory by id.

## system-aipc-portal

- Same-origin proxy endpoints so the SPA never talks to :7000 directly:
  `GET /api/v1/memories`, `POST /api/v1/memories/search`,
  `DELETE /api/v1/memories/{id}` → `http://127.0.0.1:7000`.
- Generic static file serving under `static/` (directory → `index.html`,
  path-traversal guarded) replacing the hardcoded `/` + `/assets/` routes;
  this also fixes the pre-existing 404 on Astro's `/_astro/*.js`.
- New `/memory` page (Astro, `web/src/pages/memory.astro`): semantic search,
  scope filters, memory list with per-row delete (confirm-gated). Nav link
  in `App.astro` uses `data-astro-reload`.
