# system-memory-oom-guard

Unified-memory-aware OOM watchdog. Watches total RAM pressure *and* the
GPU/NPU allocations the kernel undercounts on this 128 GB unified-memory
machine, and relieves it — **gracefully for model backends, forcefully for
apps**. Memory counterpart to `system-hardware-power-guard` (which caps
wattage).

See `openspec/changes/memory-oom-guard/` for the full design.

## What it does
- Polls `MemAvailable` + each backend cgroup `memory.current` + `rocm-smi`.
- Two-threshold hysteresis (`NORMAL → SOFT → HARD`) with hold-down seconds,
  so a model-load spike doesn't trip it.
- Classifies cgroups into `model:<backend>` or `app` by cgroup path.
- Picks a victim by a priority score (idle + class + restart-cost) — **not**
  a service whitelist. Only "kill-the-box" core units (systemd / dbus /
  login / journald / self) are hard-protected.
- Models: SOFT calls the backend unload API (Ollama `keep_alive:0`, Lemonade
  `POST /api/v0/unload`, vLLM `/sleep`); HARD `systemctl restart`s the unit.
  For Lemonade, SOFT picks among idle non-pinned loaded models by fastest
  known prefill speed first (`backends.lemonade.prefill_tok_s` in
  `config.yaml`) — cheapest to reload later. Models missing from that map
  fall back to the original last-use ordering.
- Apps: SIGTERM, escalate to SIGKILL.
- Every trigger logged to journald + `/var/lib/aipc-oom-guard/events.jsonl`
  for post-mortem.

## Status
`.disabled` — implemented to render-verified. Enabling requires a
hardware-verified claim (§9): confirm the Lemonade unload payload signature
and calibrate the thresholds against real pressure on the Strix Halo box.

## Dependencies
- `python3`, `python3-pyyaml` (packages.txt).
- `systemd` host unit (reads `/proc` + `/sys/fs/cgroup` directly — not a
  container, like `lemonade.service`).
- Consumes, read-only via each backend's HTTP **control plane** (not
  inference calls — §7 LiteLLM contract unaffected): `llm-ollama`,
  `llm-lemonade`, `llm-vllm` unload endpoints.

## Verify
`./verify.sh` — syntax + self-test (classify / priority / protected logic).
The daemon's `--self-test` runs the same assertions standalone.
