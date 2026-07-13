# How

## scheduler_hook.py

Keep the pure-logic / I/O split 0012 established (self-test runs with no
server). The reclaim decision is pure; the HTTP calls are injected.

### New env + constructor knobs

```python
COMFY_BASE = os.environ.get("AIPC_SCHED_COMFY_BASE")            # None => disabled
COMFY_RECLAIM = os.environ.get("AIPC_SCHED_COMFY_RECLAIM", "1") not in ("0", "")
```

`_SchedulerCore.__init__` gains injectable `comfy_idle` and `comfy_reclaim`
callables (default to the real HTTP impls; tests pass fakes), plus a
per-admission `_comfy_reclaimed` latch. The latch MUST be reset **inside**
`async with self.lock:`, immediately before the `while True` loop — not before
the lock. A reset before the lock is defeated by a concurrent `admit()`: while
request A holds the lock mid-loop with the latch set, request B runs its reset
before blocking on the lock, clearing A's latch and letting A `/free` a second
time. The lock already serializes admission (0012); the latch reset belongs
under it.

### Admission loop change (the only behavioural edit)

In the `while True` loop, the current tail is:

```python
victim = pick_victim(...)
if victim is not None:
    await self.post_unload(victim)
elif self._swap_admits(loaded, target):
    break
else:
    await self.sleeper(self.poll_s)
```

Insert reclaim between eviction and swap:

```python
victim = pick_victim(...)
if victim is not None:
    await self.post_unload(victim)
elif not self._comfy_reclaimed and await self._try_comfy_reclaim():
    self._comfy_reclaimed = True
    await self.sleeper(self.poll_s)      # let /free's queue flag release pages
elif self._swap_admits(loaded, target):
    break
else:
    await self.sleeper(self.poll_s)
```

`_try_comfy_reclaim()` returns True (an action was taken, re-loop) iff:
reclaim enabled AND `comfy_idle()` is truthy AND `comfy_reclaim()` succeeds.
Any exception or falsy idle → return False (fall through, degrade open). The
latch guarantees at most one `/free` per held request; if reclaim frees enough,
`_fits` breaks the loop on the next iteration; if not, the latch is spent and
the loop proceeds to `_swap_admits`/hold exactly as 0012.

When the reclaim branch fires, emit one log line naming the action and target
(`print(f"[sched] reclaimed idle ComfyUI cache before admitting {alias}", flush=True)`
or the module's logger if one exists) so the behaviour is observable — CLAUDE.md
"no silent caps" (what.md Diagnostics). This is the only observable signal that
swap-thrash was avoided; without it a reclaim is indistinguishable from a plain
swap-admit in the logs.

### I/O impls (network side, excluded from self-test)

```python
async def _http_comfy_idle():
    # GET {COMFY_BASE}/queue -> idle iff queue_running == [] and queue_pending == []
    # any error / unset base -> False
async def _http_comfy_reclaim():
    # POST {COMFY_BASE}/free {"unload_models": true, "free_memory": true}
    # 200 -> True ; error -> False
```

Both wrapped in try/except returning the conservative value; a 3–5 s timeout so
a hung ComfyUI cannot stall admission (it just fails idle/reclaim → fall
through).

### Self-test additions (`--self-test`, no server)

- reclaim fires once then latches: idle ComfyUI + no victim → one
  `comfy_reclaim` call across multiple poll iterations, not one per poll.
- reclaim precedes swap: with an evictable LLM present, victim is unloaded and
  `comfy_reclaim` is **not** called (eviction wins).
- degrade open: `comfy_idle` raising / returning False → no reclaim, loop falls
  to `_swap_admits` exactly as 0012 (regression guard on the existing path).
- disabled by default: `COMFY_BASE` unset → reclaim callable never invoked.

## quadlet/litellm.container

Add commented-optional Environment lines (host netns already shared):

```
# Environment=AIPC_SCHED_COMFY_BASE=http://127.0.0.1:8188
# Environment=AIPC_SCHED_COMFY_RECLAIM=1
```

## Complementary user-side fix (not repo scope)

Recommend to the user, documented in `llm-litellm/README.md` scheduler notes:
launch `~/ComfyUI` with `--cache-none` so it releases models after each
workflow instead of accumulating a 44 GiB GTT + 28 GiB CPU-copy footprint. On a
128 GB UMA box, re-loading a diffusion model in seconds beats grinding both swap
tiers to 100%. The gateway reclaim is the backstop for when it is *not* run that
way; the two compose.

## Verification tiers

- **Static/render:** `python3 scheduler_hook.py --self-test`, ruff, `aipc
  render bootc`, `aipc render ansible --check`. Any model can reach this.
- **Hardware (physical AI PC only):** with ComfyUI idle at a high GTT
  footprint, issue a gateway request for an LLM that does not fit → confirm one
  `/free` fired, ComfyUI GTT dropped, LLM admitted **without** swap-thrash
  (GPU busy > 0, RAM not pinned at 100%). With ComfyUI *running* a job → confirm
  reclaim does NOT fire and the job is untouched. Re-run the fdinfo aggregation
  from `gtt-hog-forensics-2026-07-14` before/after to quantify reclaimed GTT.
