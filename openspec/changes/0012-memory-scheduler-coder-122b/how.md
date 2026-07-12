# How

## Where the scheduler lives

`modules/llm-litellm/files/etc/aipc/litellm/scheduler_hook.py` — a LiteLLM
`CustomLogger` with `async_pre_call_hook`, mounted into the litellm container
next to `config.yaml` and registered via `litellm_settings.callbacks`. The
container already shares the host network namespace (it reaches lemonade on
`127.0.0.1:8001` today), so the hook can call lemonade's
`/api/v0/{health,load,unload}` directly.

New mounts in `quadlet/litellm.container`:
- `/etc/aipc/litellm/scheduler_hook.py:/app/scheduler_hook.py:ro`
- `/etc/aipc/models/models.yaml:/app/models.yaml:ro` (alias → model_id,
  size_gb, tier, pool)

Tunables come from container `Environment=` with in-code defaults:
`AIPC_SCHED_BUDGET_GB=96`, `AIPC_SCHED_COOLDOWN_S=120`,
`AIPC_SCHED_HOLD_TIMEOUT_S=900`, `AIPC_SCHED_POLL_S=2`.

## Admission algorithm (single asyncio.Lock)

```
target = manifest[data["model"]]            # miss / cloud / pool=npu → pass
health = GET /api/v0/health
if target.model_id loaded → pass
async with lock:
    deadline = now + HOLD_TIMEOUT
    while True:
        loaded = gpu models in health (manifest-known, pool != npu)
        free   = BUDGET - sum(size_gb of loaded)
        if free >= target.size_gb: break     # admit → forward request
        victims = loaded minus target, sorted:
                    floating before resident (resident only if target
                    is exclusive), then oldest last_use first,
                    skipping in_use and (age < COOLDOWN unless target
                    exclusive)
        if victims: POST /api/v0/unload victims[0]; refresh health
        else:      await sleep(POLL); refresh health
        if now > deadline: raise 503 "memory scheduler: cannot fit
                                       <alias> within budget"
```

Notes:
- The fast path (already loaded) takes no lock — steady-state chat traffic is
  unaffected.
- Serializing admissions is the thrash fix: two concurrent requests for
  different heavy models resolve one at a time against real memory state,
  instead of racing lemond into load/evict cycles.
- `health.all_models_loaded[].last_use` semantics (epoch-ms vs relative) must
  be confirmed on hardware — the existing `lemonade-idle-release.py` compares
  it against `time.monotonic()`, which looks wrong and needs the same
  hardware check (flagged, fixed alongside if confirmed).
- Failure mode: if health is unreachable the hook passes requests through
  unchanged (scheduler degrades to today's behaviour, never blocks traffic).

## Idle release + resident re-warm

`lemonade-idle-release.py` (existing daemon, systemd timer) gains:
- manifest fields `tier`/`pool` parsed alongside `idle_unload_after_s`;
- after the unload pass: if no exclusive-tier model is loaded, POST
  `/api/v0/load` for each `tier: resident` model not currently loaded (one
  per cycle, smallest first, and only if it fits the same budget arithmetic —
  re-warm must not itself evict anything).

`coder-122b` release is just `idle_unload_after_s: 600` on its manifest entry.

## coder-122b registration

Same custom-registration pattern as ornith/coder-agentic (`user.` prefix,
checkpoints main+mmproj now expressible in models.yaml for `aipc models
sync`). Load recipe: `--llamacpp vulkan --ctx-size 131072`,
`--llamacpp-args "-np 1 -kvu"` — single stream: a 55 GiB working set should
not multiply KV slots, and coding sessions are effectively single-user.
litellm entry mirrors `coder-agentic` (`enable_thinking: false`,
`timeout: 1800`, `num_retries: 0`, `max_input_tokens: 262144`).

## Hardware findings folded back in (2026-07-12 live verification)

- **Budget 96 → 80.** The non-model working set on this box measured ~47GB
  (desktop + hermes + services), not the ~25GB the 96 figure assumed; 96
  would have admitted ornith + coder-122b together and OOMed real RAM.
- **Recipe options MUST be pinned before a big model's first load.** With no
  saved options, lemonade loads at the model-card ctx (262144); for the
  122B that exhausted GTT and took down every GPU context on the box
  (llama-server SIGABRT via vk::DeviceLostError, zen SIGSEGV, lemond
  SIGSEGV, kwin GL_CONTEXT_LOST, plasmashell wedged). Pin by writing
  `recipe_options.json` directly (no load needed), then restart lemonade.
- **`--no-warmup` is required in the 122B recipe.** The empty-run warmup
  measured 8.5 min — past lemonade's `global_timeout` (600s ready-wait), so
  loads fell into a timeout-kill-retry loop. `--no-warmup` makes ready
  fast; the first real request pays the warmup. configure-lemonade.sh also
  raises `global_timeout` to 1800 for the next image build (the live /usr
  copy resets 600 on every service start until then).

## What this does NOT do

- No lemond-side changes: `max_loaded_models` stays 4 (count ceiling as a
  backstop); the scheduler is purely additive at the gateway.
- Direct-to-:8001 callers (allowed only inside `modules/llm-*` per §7) bypass
  the scheduler — acceptable: the portal only polls `/health`, and pulls
  don't load models.
