# How

- mem0ai==2.0.11 `Memory.get_all()` raises `ValueError` unless filters
  contain one of `user_id`/`agent_id`/`run_id` (confirmed against the live
  service), which forbids exactly the "browse everything" case a management
  UI needs. `get_all()` is only that validation + telemetry around
  `Memory._get_all_from_vector_store()`, so `GET /memories` calls the
  internal directly; pgvector's `list()` treats an empty filters dict as
  "no WHERE clause" (verified live against real data).
- The portal proxy reuses the existing stdlib `urllib` pattern (same as the
  automation-cancel proxy); `do_DELETE` added to the handler, memory ids
  validated with the existing `_safe_id` (UUIDs pass).
- Frontend follows `index.astro`'s vanilla-JS style; built via
  `npm run build` in `web/` and `dist/` copied into
  `files/usr/lib/aipc-portal/static/` per the module README.
