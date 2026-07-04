# How: Implementation Details for the OOM Guard

## 1. Pressure inputs (unified-memory-aware)

Every `poll_interval` (default 1 s):
- `MemAvailable` from `/proc/meminfo`.
- Each known backend cgroup `memory.current`:
  `/sys/fs/cgroup/system.slice/{lemonade,ollama}.service/memory.current`.
- GPU/NPU: `rocm-smi --showmeminfo vram` (iGPU) and the NPU allocator
  where exposed — so allocations the kernel undercounts are still seen.

Threshold defaults (all tunable, calibrate on hardware):
`soft_bar` ≈ 10% of RAM (~12 GB), `hard_bar` ≈ 3% (~4 GB),
`T_soft` ≈ 10 s, `T_hard` ≈ 3 s.

## 2. State machine

`NORMAL → SOFT` when `MemAvailable < soft_bar` for `T_soft`.
`SOFT → HARD` when `< hard_bar` for `T_hard`.
Any state → `NORMAL` when pressure clears for `T_soft`.
On a transition: snapshot top-N memory cgroups → classify → score → act.

## 3. Classification + priority

Class by cgroup path: under `system.slice/{lemonade,ollama,vllm}.service`
→ `model:<backend>`; else `app`.

Priority score (lower = evicted first): base on `idle_seconds` (longer
idle = lower) adjusted by class (apps rank below models) and restart-cost
(smaller / non-pinned models below large / pinned). Pinned models
(Lemonade reports `pinned:true` in `/api/v0/health`) are skipped in SOFT.

Anti-self-kill: never target the guard's own cgroup, display / login /
journald units, or PID < 500.

## 4. Relief actors

- **Ollama** model: `POST /api/generate` with `keep_alive: 0` for the
  victim checkpoint (pattern already used in `llm-litellm` config).
- **Lemonade** model: `POST /api/v0/unload` (endpoint verified to exist —
  returns 405 on GET against the running `lemonade.service` on 2026-07-04).
  Payload signature to be confirmed on hardware.
- **vLLM** model (when enabled): `POST /sleep` (upstream sleep mode).
- **model HARD**: `systemctl restart <backend>.service`.
- **app SOFT/HARD**: `SIGTERM`, escalate to `SIGKILL` after a grace period.

## 5. Event log

One JSON line per action to journald (`journalctl -u oom-guard`) and a
ring buffer `/var/lib/aipc/oom-guard/events.jsonl`:
`{ts, level, mem_before, mem_after, gpu_vram_before, gpu_vram_after,
  target_cgroup, target_pid, class, action, result, reason}`.

## 6. Deployment

Plain systemd unit (not a quadlet) — like `lemonade.service`, because the
guard must read host `/sys/fs/cgroup` + `/proc` directly. Registers a row
in `ops-doctor` `services.yaml`; the guard is usable independently of
doctor (doctor is currently `.disabled`).

## Decisions

- **Per-backend control API, not LiteLLM.** LiteLLM is a stateless proxy
  with no backend-lifecycle handle (verified against pinned tag v1.89.4,
  recorded in `llm-litellm/README.md`). *Alternative considered:* route
  unload through LiteLLM — rejected, structurally impossible; the
  control plane is also not an inference call, so §7 is unaffected.
- **Priority scoring, not a service whitelist.** Most "critical" services
  aren't built yet, so a whitelist would rot. *Alternative considered:*
  hardcoded protected-services list — rejected for now; revisit if a
  service needs guaranteed protection beyond anti-self-kill.
- **Dual threshold + hysteresis, not a single line.** A single line trips
  on every model-load spike. *Alternative considered:* single hard
  threshold — rejected, too many false kills during normal model loads.

## Risks

- **Risk:** unified-memory pressure signal is still imperfect →
  **Mitigation:** fuse three sources (`MemAvailable` + cgroup
  `memory.current` + `rocm-smi`); calibrate thresholds on hardware (AI PC).
- **Risk:** Lemonade unload payload unknown → **Mitigation:** endpoint
  existence hardware-verified (405 on GET); payload confirmed in an
  (AI PC) task before depending on it; HARD restart is the fallback if
  unload misbehaves.
- **Risk:** kills a critical process → **Mitigation:** anti-self-kill
  rules + priority scoring; every kill logged for post-mortem.
- **Risk:** wrong thresholds cause thrash or late action →
  **Mitigation:** all thresholds tunable with documented defaults;
  (AI PC) calibration task.
