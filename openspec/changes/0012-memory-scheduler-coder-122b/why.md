# Why: A 122B Coding Model Cannot Coexist With The Agent Fleet, And Lemonade's Blind Load Queue Still Thrashes

Two forcing functions, observed/decided 2026-07-12:

1. **The user wants `coder-122b`** —
   `SC117/Qwen3.5-122B-A10B-Uncensored-APEX-Compact-GGUF` (55.1 GiB weights +
   0.8 GiB mmproj, 122B total / 10B active MoE, 262K ctx) as the heavy coding
   model. On this 128 GB UMA box (GTT ceiling 122 GiB, desktop + services
   already consume tens of GB), loading it next to the 0011 steady-state
   resident set (`qwythos-9b` 5.6 + `assistant-gemma` 16 + `coder-agentic` 22
   ≈ 43 GiB) is guaranteed OOM or degraded fit. The predecessor
   (`qwen35-122b-q3` on Ollama, 81 GB) was retired 2026-07-11 for exactly
   "hard to run comfortably"; re-adding a 122B is only viable if something
   *makes room deterministically before the load happens*.

2. **Lemonade's load queue has no admission control.** 0011 removes the
   biggest thrash *drivers* (lane fan-out, self-improve boot pass), but the
   mechanism that turned those drivers into a meltdown remains: lemond
   auto-loads whatever model any request names, serially, with no notion of
   memory budget or priority. Hardware-observed 2026-07-12 (this session): a
   wedged queue kept cycling 7 distinct model loads for 40+ minutes *after
   every caller service was already stopped*, starving an unrelated
   `lemonade pull` indefinitely; only restarting lemonade+litellm cleared it.
   Count-based `max_loaded_models=4` cannot see that 122B + residents exceeds
   physical memory — slots are not gigabytes.

Both problems have the same answer: the LiteLLM gateway is the single choke
point every consumer is already required to use (CLAUDE.md §7). Admission
control belongs there — decide *before* lemond ever sees a request whether the
target model fits, evict by priority if it doesn't, and hold the request until
it does. lemond then only ever receives loads that are known to fit, which is
what "遏止 thrash" means structurally, not just for the 122B case.
