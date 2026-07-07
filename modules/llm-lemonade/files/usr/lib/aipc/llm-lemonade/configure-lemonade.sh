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
  jq '.max_loaded_models = 2 | .enable_dgpu_gtt = true | .llamacpp.backend = "vulkan"' "$CFG" > "$tmp"
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
