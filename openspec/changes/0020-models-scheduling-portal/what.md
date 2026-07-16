# What — models-scheduling-portal

- New page `/models` + nav link.
- `GET /api/v1/models` returns policy, capacity gates, loaded model decisions
  (keep_warm / in_use / cooling / unload_candidate), catalog idle policy,
  idle-release journal tail, OOM-guard event ring.
- Read-only; never triggers load/unload.
