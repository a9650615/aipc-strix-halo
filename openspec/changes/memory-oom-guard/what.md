# What: Unified-Memory-Aware OOM Guard Module

The `system-memory-oom-guard` module runs a lightweight daemon that watches
total memory pressure (system RAM **and** GPU/NPU allocations), and when
pressure crosses two thresholds it relieves it — **gracefully for model
backends, forcefully for apps**.

It is the memory counterpart to `system-hardware-power-guard` (which caps
*wattage*). Same layer, different signal.

## Components

1. **Pressure monitor** — polls `MemAvailable` + each backend cgroup's
   `memory.current` + `rocm-smi` / NPU allocator, so unified-memory
   allocations are seen, not just RSS.
2. **Hysteresis state machine** — `NORMAL → SOFT → HARD`, dual thresholds
   with hold-down seconds (avoids tripping on a model-load spike).
3. **Classifier** — maps top-memory cgroups to `model:<backend>` or `app`
   by cgroup path (`/system.slice/lemonade.service`,
   `/system.slice/ollama.service`, …).
4. **Priority scorer** — picks victims by a score blending idle/recency +
   class + restart-cost; **not** a hardcoded service whitelist.
5. **Relief actors**:
   - model SOFT → backend control API (Ollama `keep_alive:0`, Lemonade
     `POST /api/v0/unload`, vLLM `POST /sleep`)
   - model HARD → `systemctl restart` the backend unit
   - app SOFT → SIGTERM; app HARD → SIGKILL
   - never targets self / display / login / journald / PID<500
     (anti-self-kill)
6. **Event log** — one structured JSON line per trigger to journald +
   `/var/lib/aipc/oom-guard/events.jsonl` ring buffer, for post-mortem.

## Capabilities

- Adds capability: `system-memory-oom-guard`.
- No existing capability modified.
- Consumes (read-only, via each backend's HTTP **control plane** — not
  inference calls, so the §7 LiteLLM contract is unaffected) the unload
  endpoints of `llm-ollama`, `llm-lemonade`, `llm-vllm`.

## Specification Diffs (Targeting Modules)

New module: `modules/system-memory-oom-guard`. No edits to other modules'
files. Deployment adds one systemd/quadlet service and one optional row
in `ops-doctor`'s `services.yaml` registry.
