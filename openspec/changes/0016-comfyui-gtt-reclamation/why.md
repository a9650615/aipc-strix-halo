# Why: The Scheduler's "Lean On Swap" Stopgap Became The Failure It Was Meant To Avoid

0012's admission control evicts LLM victims by priority, then — when the only
thing still blocking the real-memory gate is **non-LLM** memory it cannot evict
(ComfyUI's diffusion models, which the user keeps) — falls back to
`_swap_admits`: admit the LLM load anyway if free swap can absorb it. That was
the 2026-07-13 directive ("swap is fine, OOM is not").

Hardware forensics 2026-07-14 show that fallback *is* the meltdown, not the
escape from it. Per-process DRM fdinfo (`drm-memory-gtt`, de-duped by
`drm-client-id`) at a wedged moment:

| Process | GTT | + RSS | + swap | ≈ footprint |
|---|---|---|---|---|
| **ComfyUI** (`main.py --reserve-vram 24`) | 44.3 GiB | 28.2 GiB | 18.6 GiB | **~91 GiB** |
| llama-server (Gemma4-26B-A4B) | 15.2 GiB | — | 1.9 GiB | ~17 GiB |
| ollama (0 models) / flm (NPU) | 0 | — | 4.1 GiB | — |

Global GTT 59.8 / 122 GiB, RAM 121/121 full, zram 47.8/48 full, nvme swap
starting to fill. GPU busy **6%** while a job "ran" — the box was not
computing, it was swap-thrashing. The user's suspicion was right: it is **not**
"too many LLMs" (there is exactly one llama-server, one model). The single GTT
hog is ComfyUI, and swap-admitting an LLM *on top of* a 91 GiB ComfyUI footprint
is what drove RAM+zram to 100% and the box into thrash.

Two facts make a better answer possible than "hold or swap-thrash":

1. **ComfyUI's cache is reclaimable on demand.** It exposes
   `POST /free {"unload_models":true,"free_memory":true}` (queue-flagged,
   takes effect after the current job) and `GET /queue` to tell whether it is
   idle. Its default behaviour is to *cache every loaded model and keep a CPU
   weight copy* — the 28 GiB RSS + 18.6 GiB swap — which `--reserve-vram` does
   not bound (that flag only tunes torch headroom, not cache retention).

2. The scheduler already probes host memory every cycle. Reclaiming an **idle**
   ComfyUI's cache before resorting to swap turns "block the LLM or thrash the
   whole box" into "free the memory that is actually recoverable, then admit
   normally" — reclaim a few tens of GiB in seconds versus grinding both swap
   tiers to 100%.

ComfyUI is the user's own install (`~/ComfyUI`, not a repo module, not a
systemd unit), so the durable fix lives at the gateway the scheduler already
owns, not in ComfyUI's launch args.
