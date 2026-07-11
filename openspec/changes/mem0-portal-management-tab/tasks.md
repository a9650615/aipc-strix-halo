# Tasks for mem0-portal-management-tab

- [x] 1.1 memory-mem0: add `GET /memories` (unscoped-capable list) + `DELETE /memories/{id}` to `aipc_mem0/server.py`, with contract tests
- [x] 1.2 system-aipc-portal: mem0 proxy endpoints (`/api/v1/memories*`) + generic static serving with traversal guard, with server tests
- [x] 1.3 system-aipc-portal: `/memory` Astro page + nav link + styles; rebuild `web/dist` into `static/`
- [x] 1.4 Render-verify both targets (`aipc render bootc` / `render ansible`)
- [x] 1.5 (AI PC) Hardware-verify: live-hotfix mem0 (`/etc/aipc/mem0`), add→list→delete→search against real pgvector data; portal end-to-end (page, nav, proxies, delete flow)
