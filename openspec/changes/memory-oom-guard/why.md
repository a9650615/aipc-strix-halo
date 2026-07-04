# Why: Model + APP Memory Pressure Can Lock Up the Whole Machine

This is a 128 GB **unified** memory machine: the Lemonade (NPU) and Ollama
(iGPU) model backends allocate GPU/NPU memory *out of system RAM*, and
ordinary apps compete for the same pool. Two failure modes today:

1. **The kernel OOM killer reacts too late.** `systemd-oomd` / `earlyoom`
   watch RSS and `MemAvailable`. On unified memory, a model can pin a large
   block as GPU/NPU allocation that the kernel does not fully account as
   pressure until the box is already thrashing — by then the swap-storm
   stalls the whole desktop/voice/agent stack.
2. **A blind kill hits the wrong target at the wrong cost.** Killing a
   model backend means a cold weight reload (tens of seconds to minutes)
   and drops every in-flight inference request; killing a runaway app is
   cheap. The backends have *passive, per-engine* idle eviction today
   (`OLLAMA_KEEP_ALIVE`, Lemonade's unload policy) but nothing watches
   total system pressure or coordinates a graceful-model / hard-app
   response.

We need an active, unified-memory-aware guard that detects pressure early
and applies **different** actions to models vs apps.
