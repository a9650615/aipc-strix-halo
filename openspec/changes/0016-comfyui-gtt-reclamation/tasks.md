# Tasks

- [x] 1.1 scheduler_hook.py: add `AIPC_SCHED_COMFY_BASE` / `AIPC_SCHED_COMFY_RECLAIM`
      env + injectable `comfy_idle`/`comfy_reclaim` on `_SchedulerCore`; insert
      the reclaim branch between eviction and `_swap_admits` with a
      per-admission latch (`_comfy_reclaimed` reset in `admit()`).
- [x] 1.2 scheduler_hook.py: `_http_comfy_idle` (GET /queue, idle iff running
      and pending both empty) + `_http_comfy_reclaim` (POST /free
      unload_models+free_memory), both try/except → conservative value, 3–5s
      timeout. Excluded from self-test.
- [x] 1.3 scheduler_hook.py `--self-test`: reclaim-fires-once-then-latches,
      reclaim-precedes-swap (eviction wins when a victim exists),
      degrade-open (idle raises/False → falls to swap as 0012),
      disabled-when-BASE-unset. Runs with no server.
- [x] 1.4 quadlet/litellm.container: commented-optional COMFY_BASE/COMFY_RECLAIM
      Environment lines; confirm host netns reaches 127.0.0.1:8188.
- [x] 1.5 llm-litellm README: document reclaim step + the user-side
      `--cache-none` recommendation for `~/ComfyUI`.
- [x] 1.6 Static + render: self-test/ruff green, `aipc render bootc`,
      `aipc render ansible --check` both green and in sync (§4).
- [ ] 2.1 HW (physical AI PC): ComfyUI idle at high GTT → gateway LLM request
      that does not fit → exactly one `/free` fired, ComfyUI GTT dropped, LLM
      admitted without swap-thrash (GPU busy > 0, RAM not pinned 100%).
      Quantify with fdinfo aggregation before/after (gtt-hog-forensics method).
- [ ] 2.2 HW: ComfyUI *running a job* → reclaim does NOT fire, job untouched,
      request falls to swap/hold as before.
- [ ] 2.3 HW: ComfyUI stopped/unreachable → reclaim skipped silently, loop
      behaves exactly as 0012 (no new failure mode).
