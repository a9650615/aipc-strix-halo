#!/bin/sh
# configure-lemonade.sh — llm-lemonade
# Idempotent config.json merge, run by lemonade.service's ExecStartPre on
# the host, before the container starts (the file lives on the
# bind-mounted cache dir below). Hardware-verified 2026-07-05: default
# config.json has max_loaded_models=1 (coder-agentic and ornith-35b can't
# both stay resident) and enable_dgpu_gtt=false (the ROCm backend's
# allocator can't cross the 4GB VRAM carve-out into GTT without it — see
# README). Skips silently if config.json doesn't exist yet (first-ever
# boot: lemond creates it with defaults, and this merge then takes effect
# starting the next restart — Restart=always guarantees that happens).
# llamacpp.backend=vulkan pins the auto-load backend choice to the one
# that actually measured fastest on this hardware (see README).
#
# A plain shell one-liner in ExecStartPre= hit systemd's own unit-file
# quoting rules mangling jq's nested quotes (the literal string "vulkan"
# lost its quotes and jq mis-parsed it as a field reference) — a real
# script file sidesteps that entirely.
#
# mktemp deliberately NOT used bare (default /tmp): this unit's plain
# systemd service runs as init_t, which has no write access to tmp_t —
# hardware-verified 2026-07-05 via `ausearch -m avc` showing
# `denied { write } ... tcontext=system_u:object_r:tmp_t:s0` — same class
# of SELinux-vs-custom-systemd-unit gap documented elsewhere in this repo
# (init_t has no write access to several path types by default). Writing
# the temp file next to config.json instead (container_file_t, which
# init_t can already write given the ExecStartPre mkdir above succeeds)
# avoids tmp_t entirely.
set -eu

CFG=/var/lib/aipc-lemonade/cache/config.json

if [ -f "$CFG" ]; then
  tmp=$(mktemp -p "$(dirname "$CFG")")
  # High slot count: 128GB unified memory — keep FLM + several Vulkan LLMs
  # resident. Pin the resident-small FLM model via ensure-resident-small.sh so LRU never
  # evicts the always-on chat model. Do not thrash by unloading big models.
  # FLM is type=llm in this lemond build and counts against the pool.
  #
  # Hardware-verified 2026-07-11: lemond 10.8.1's `/api/v1/health` reports a
  # per-type `max_models: {llm, embedding, ...}` breakdown, but there is no
  # separate per-type config.json key backing it — read the lemond binary's
  # symbols (RuntimeConfig::max_loaded_models(), Router::get_max_model_limits())
  # and confirmed live: setting only `max_loaded_models` here makes every
  # `max_models.<type>` in the health response mirror that same number
  # (max_loaded_models=8 -> max_models.llm=8, verified with 3 LLMs resident
  # simultaneously, no eviction, no swap thrashing). A machine whose live
  # `/api/v1/health` still shows `max_models.llm: 2` almost certainly has a
  # stale pre-fix copy of this script deployed (compare
  # /usr/lib/aipc/llm-lemonade/configure-lemonade.sh's mtime/content against
  # this repo file, see docs/live-hotfix-workflow.md) rather than a real
  # 10.8.1 schema change requiring a new key.
  #
  # 8 -> 4 (OOM 2026-07-11) -> 2 (SMO 2026-07-16): multi-auto-load thrash
  # with 122B + mid models left MemAvailable~0 / GTT 70Gi+ / swap 60Gi+.
  # FLM (resident-small, NPU) counts as type=llm in lemond 10.8.1, so
  # max_loaded_models=2 == pinned NPU + ONE GPU LLM. Gateway SMO enforces
  # the same single-GPU-slot policy; do not raise without re-proving UMA.
  # global_timeout 1800: coder-122b ready-wait (0012).
  jq '.max_loaded_models = 2 | .enable_dgpu_gtt = true | .llamacpp.backend = "vulkan" | .global_timeout = 1800' "$CFG" > "$tmp"
  mv "$tmp" "$CFG"
fi

# Ensure coder-122b's Lemonade id is registered (weights live under HF hub
# bind-mount; without this entry lemond 404s "Model was not found" even when
# GGUF is on disk — hardware-verified 2026-07-16 dry-run).
UM=/var/lib/aipc-lemonade/cache/user_models.json
if [ -f "$UM" ]; then
  tmpu=$(mktemp -p "$(dirname "$UM")")
  jq '
    .["Qwen3.5-122B-A10B-Uncensored-APEX-Compact"] = (
      .["Qwen3.5-122B-A10B-Uncensored-APEX-Compact"] // {
        "checkpoints": {
          "main": "SC117/Qwen3.5-122B-A10B-Uncensored-APEX-Compact-GGUF:Qwen3.5-122B-A10B-Uncensored-APEX-Compact.gguf",
          "mmproj": "SC117/Qwen3.5-122B-A10B-Uncensored-APEX-Compact-GGUF:mmproj-Qwen3.5-122B-A10B-Uncensored-HauhauCS-Aggressive-f16.gguf"
        },
        "labels": ["custom", "tool-calling", "exclusive"],
        "recipe": "llamacpp",
        "suggested": true
      }
    )
  ' "$UM" > "$tmpu"
  mv "$tmpu" "$UM"
fi
