# Tasks

- [x] 1.1 models.yaml: add `coder-122b` entry (checkpoints main+mmproj,
      `tier: exclusive`, `idle_unload_after_s: 600`); add `tier: resident` to
      qwythos-9b / assistant-gemma / coder-agentic; `pool: npu` to
      resident-small; `tier: floating` default documented.
- [x] 1.2 litellm config.yaml: `coder-122b` model entry
      (enable_thinking false, timeout 1800, num_retries 0, max_input 262144)
      + `litellm_settings.callbacks` registration.
- [x] 1.3 scheduler_hook.py: admission control per how.md, with pure-logic
      self-test (fit math, victim ordering, cooldown, exclusive preemption,
      hold timeout) runnable without a server.
- [x] 1.4 quadlet/litellm.container: mount scheduler_hook.py + models.yaml,
      Environment tunables.
- [x] 1.5 lemonade-idle-release.py: parse tier/pool; resident re-warm pass
      (budget-checked, one per cycle); extend self-test.
- [x] 1.6 llm-lemonade verify.sh: coder-122b pulled check; llm-litellm
      verify.sh (if present) or README: scheduler wiring documented.
- [x] 1.7 Static + render: pytest/self-tests, `aipc render bootc`,
      `aipc render ansible` both green.
- [x] 2.1 HW: confirm `last_use` semantics from live `/api/v0/health` — it is
      host CLOCK_MONOTONIC in ms (hardware-checked 2026-07-12: value matched
      a request ~100s prior against /proc/uptime), so idle-release's
      `time.monotonic() - last_use/1000` comparison is CORRECT; no fix.
      Note: idle `status` is "ready", busy detection relies on "in_use"
      (unverified under live generation load — watch during 2.3/2.4).
- [x] 2.2 HW (2026-07-12): pulled + loaded + chat 200 via gateway; decode
      26.8 tok/s, TTFT 1.2s, 400-token completion in 19s. Required two
      folded-back fixes first (see how.md hardware findings): pinned
      recipe (ctx 131072, -np 1 -kvu, --no-warmup) and budget 96→80 —
      the unpinned first load (ctx 262144) exhausted GTT and DeviceLost'd
      the whole desktop (llama-server/zen/lemond crashes, kwin
      GL_CONTEXT_LOST, plasmashell wedged).
- [x] 2.3 HW (2026-07-12): preemption observed twice — held 122B request
      evicted idle ornith within 2s of its slot freeing, then loaded;
      lemond queue stayed empty throughout (no blind load queued).
- [x] 2.4 HW (2026-07-12): hold verified — while ornith was in_use the
      122B request was held at the gateway (no lemond activity), admitted
      only after the slot freed. Small-model coexistence verified:
      qwythos admitted into leftover budget alongside the loaded 122B
      (59.2+5.6 ≤ 80), answered in 8s, 122B untouched.
- [x] 2.5 HW (2026-07-12): release + re-warm verified with a manual unload
      standing in for the 600s expiry (expiry itself reuses the proven
      0006 _expired_candidates path): daemon no-ops while the exclusive
      model is loaded, then re-warms assistant-gemma and coder-agentic on
      successive cycles until the 0011 resident set is restored.
- [ ] 2.6 HW: soak an idle hour — zero unsolicited load/evict cycles
      (thrash gone), journald clean. (Pending: run after the 0011 lane
      consolidation lands; today's lanes still hammer ornith when idle.)
