# What: Reclaim Idle ComfyUI Cache Before Swap-Backed Admission

Insert one step into 0012's admission loop, between "no evictable LLM remains"
and the `_swap_admits` swap fallback: if a reachable ComfyUI is **idle**, ask
it to free its cache, re-check fit, and only fall through to swap if reclaim
did not open enough room (or ComfyUI is busy / unreachable).

## Scheduler behaviour (scheduler_hook.py)

New admission-loop ordering when the target still does not fit after evicting
every eligible LLM victim:

1. **Reclaim** — if ComfyUI is configured, reachable, and `GET /queue` shows
   no running + no pending job, `POST /free {"unload_models":true,
   "free_memory":true}` **at most once per admission** (a reclaim latch, so a
   held request does not spam `/free` every poll). Re-loop and re-check fit
   after the daemon has had a poll interval to release pages.
2. **Swap-admit** — unchanged `_swap_admits` fallback, reached only if reclaim
   was impossible (ComfyUI busy/unreachable/absent) or insufficient.
3. **Hold** — unchanged; deadline + 503 as before.

Constraints:

- **Never interrupt a running job.** Reclaim fires only when `/queue` is empty;
  a busy ComfyUI is treated exactly as today (fall to swap/hold). The user is
  the ComfyUI operator — the scheduler must not kill their work to load an LLM.
- **Degrade open.** ComfyUI unreachable, unset, or `/queue`/`/free` errors →
  skip reclaim silently and fall through. The scheduler never becomes an outage
  and never depends on ComfyUI being up.
- **Reclaim precedes swap, not eviction.** LLM victims are still evicted first
  (an idle floating LLM is cheaper to reload than a diffusion model); reclaim
  only displaces the *swap-thrash* fallback, which forensics show is the harm.

## New env tunables (defaults keep current behaviour if unset → disabled)

- `AIPC_SCHED_COMFY_BASE` — ComfyUI base URL (e.g. `http://127.0.0.1:8188`).
  **Unset → reclaim disabled**, loop behaves exactly as 0012 today.
- `AIPC_SCHED_COMFY_RECLAIM` — `1`/`0` master toggle (default `1` when BASE set).

Wired into `quadlet/litellm.container` as commented-optional Environment lines
(the container shares the host network namespace, so `127.0.0.1:8188` reaches
the user's ComfyUI).

## Diagnostics

- `aipc doctor` / a scheduler log line naming a reclaim action ("reclaimed idle
  ComfyUI cache before admitting <alias>") so the behaviour is observable, per
  CLAUDE.md "no silent caps".
- Memory `gtt-hog-forensics-2026-07-14` records the fdinfo aggregation method
  for re-diagnosis.

## Out of scope (user-side, documented not implemented)

- ComfyUI `--cache-none` launch flag and `--reserve-vram` retuning are the
  user's personal `~/ComfyUI` setup, not a repo module. Recommended in
  `how.md` as the complementary front-line fix (stop accumulating cache at the
  source) but not owned by this change.

## Capability Impact

- `ai-runtime`: admission control gains a reclaim step for non-evictable,
  externally-reclaimable GPU memory (ComfyUI), so swap-backed admission is a
  genuine last resort rather than the first response to ComfyUI pressure.
