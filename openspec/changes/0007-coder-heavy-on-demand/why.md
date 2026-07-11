# Why: A Heavy Coding Model That Exists Only While It Is Needed

The fleet has no big-model lane. `qwen35-122b-q3` (Qwen3.5-122B, ~81GB Q3 on
Ollama) was retired 2026-07-11 because it was uncomfortable to run and
duplicated a giant model across backends. Since then the strongest local
option is a 35B-A3B — fine for tool loops, but there are tasks (hard
refactors, long-context reviews, design work while offline) where a
100B-class model is materially better.

Two facts make this cheap now:

1. **This machine needs no offload tricks.** `amdgpu.gttsize=125000` gives the
   iGPU 122 GiB of addressable unified memory (checked live 2026-07-12).
   A ~46GB Q4 MoE loads whole; expert/layer/SSD offloading — all designed for
   discrete-GPU memory splits — would only slow it down here, because CPU and
   GPU share the same ~256 GB/s LPDDR5X bus.
2. **The idle-release mechanism already exists.** Change 0006 made
   `idle_unload_after_s` a data-driven per-alias policy. A heavy on-demand
   alias is exactly the consumer that mechanism was designed to generalize to:
   loaded on first request, gone N minutes after the last one.

The real constraint is not capability but co-residency: with the current
fleet loaded, `MemAvailable` was ~24GB (checked live 2026-07-12). Lemonade's
LRU evicts by model *count* (`max_loaded_models=4`), not by bytes, so loading
a 46GB model can OOM even when a slot is free. The residency policy therefore
has to be part of this change, not an afterthought — that is the repeated
lesson from `configure-lemonade.sh`'s own history (max_loaded_models=8
invoked the oom-killer).
