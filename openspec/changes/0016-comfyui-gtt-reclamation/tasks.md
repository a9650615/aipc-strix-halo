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
- [x] 1.7 大哥 review fixes: (a) move `_comfy_reclaimed = False` INSIDE
      `async with self.lock:` before the `while True` loop — the current
      pre-lock reset is defeated by a concurrent `admit()` (double `/free`);
      (b) add the reclaim-fired log line (what.md Diagnostics, no-silent-caps);
      (c) extend self-test with a concurrent-admit case proving the latch holds
      across two overlapping admissions (exactly one reclaim). Re-run the four
      static/render gates.
- [x] 2.1 HW (physical AI PC, 2026-07-14): ComfyUI (throwaway instance)
      loaded sd_xl_base_1.0 (idle queue), GTT 9.33GB, host MemAvailable
      71.65GB. Gateway request for `qwythos-9b` (test-scoped
      `AIPC_SCHED_HEADROOM_GB=70` to force the real-mem gate to bind on
      this machine's large 121GB/88GB-avail baseline) logged
      `[sched] reclaimed idle ComfyUI cache before admitting qwythos-9b`
      exactly once; ComfyUI GTT dropped 9.33GB -> 1.9GB within the poll
      cycle, MemAvailable rose to 74.1GB; request admitted HTTP 200 in
      6.0s (GPU busy read back at 6% post-completion, no thrash).
- [x] 2.2 HW (2026-07-14): submitted a real 40-step/1024px SDXL job so
      `/queue` was non-empty, then fired the same admission pressure
      (`assistant-gemma`) immediately. litellm log shows zero reclaim
      lines while the job ran; the ComfyUI job completed untouched
      (`history` status `success`, output PNG written). A reclaim line
      appeared only after the queue went idle (next poll iteration),
      confirming `comfy_idle` correctly gated on queue state, not just a
      timer.
- [x] 2.3 HW (2026-07-14): pointed `AIPC_SCHED_COMFY_BASE` at a dead port
      (127.0.0.1:8199) while the real ComfyUI (127.0.0.1:8188) stayed up
      with 9.7GB cached; gateway request for `qwythos-9b` returned HTTP
      200 in 3.2s via swap-admit, zero reclaim log lines, and ComfyUI's
      real GTT was unaffected (9.7GB before -> 15.0GB after, entirely
      explained by qwythos-9b's own GPU load, i.e. ComfyUI's cache was
      never touched) — degrades open exactly as 0012, no new failure mode.
      Live env restored to production (`COMFY_BASE=:8188`,
      `HEADROOM_GB=10`) and verified with a follow-up sanity chat call
      (HTTP 200) before repo apply.
