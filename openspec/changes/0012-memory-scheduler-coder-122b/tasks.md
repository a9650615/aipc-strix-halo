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
- [ ] 2.2 HW: pull coder-122b (55.1 GiB), load, single chat via gateway.
- [ ] 2.3 HW: preemption — with residents loaded, request coder-122b →
      residents unload first, 122B loads, no OOM, no lemond queue churn.
- [ ] 2.4 HW: hold — concurrent small-model request during a 122B session
      waits or fits (qwythos fits in leftover budget) instead of evicting
      the in-use 122B.
- [ ] 2.5 HW: idle release at 600 s + resident set re-warmed afterwards.
- [ ] 2.6 HW: soak an idle hour — zero unsolicited load/evict cycles
      (thrash gone), journald clean.
