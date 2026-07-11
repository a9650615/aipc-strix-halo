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
  # resident. Pin gemma4-it-e4b-FLM via ensure-resident-small.sh so LRU never
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
  # 8 -> 4 (hardware-verified OOM 2026-07-11 22:49): with 8 slots nothing
  # ever evicts, so LLMs accumulate — observed 5 resident (35B + 26B +
  # VL-7B + E2B + NPU FLM) = 60 GiB GTT; with ComfyUI alongside, RAM hit
  # 121/121 + swap 15/15 full and the kernel OOM killer fired
  # (llama-server invoked oom-killer). 4 = pinned NPU FLM + coder-agentic
  # (35B) + coder-compact (E2B) + one floating slot (ornith-35b advisor /
  # vlm / daily); a 5th load LRU-evicts the floater (~5-12s reload) instead
  # of OOMing the box. Derive this number from the memory budget, never
  # set it "generously".
  jq '.max_loaded_models = 4 | .enable_dgpu_gtt = true | .llamacpp.backend = "vulkan" | .global_timeout = 600' "$CFG" > "$tmp"
  mv "$tmp" "$CFG"
fi

# Qwen 3.5-122B moved to Ollama 2026-07-07 to avoid Lemonade slot-tracking bug
# (see models.yaml comment). Remove from user_models.json so lemond won't
# auto-load it on startup — same slot issue that caused the crash.
UM=/var/lib/aipc-lemonade/cache/user_models.json
if [ -f "$UM" ]; then
  tmp2=$(mktemp -p "$(dirname "$UM")")
  jq 'del(.["Qwen3.5-122B-A10B-GGUF-Q3_K_XL"])' "$UM" > "$tmp2"
  mv "$tmp2" "$UM"
fi
