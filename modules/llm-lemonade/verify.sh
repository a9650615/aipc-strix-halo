#!/bin/sh
# verify.sh — llm-lemonade
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# NPU device node exists
[ -e /dev/accel/accel0 ] || fail "llm-lemonade: /dev/accel/accel0 not found (amd-xdna driver not loaded?)"

# Plain systemd unit (not a quadlet) is active
systemctl is-active --quiet lemonade.service \
  || fail "llm-lemonade: lemonade.service not active"

# API responds — hardware-verified 2026-07-04 both /health and
# /api/v1/health return 200 on the real container image.
port=$(cat /etc/aipc/env.d/llm-lemonade/port 2>/dev/null || echo "8001")
curl -fsS "http://127.0.0.1:${port}/health" >/dev/null 2>&1 \
  || fail "llm-lemonade: API not responding on 127.0.0.1:${port}"

# resident-small (FLM/NPU), coder-agentic, and ornith-35b must actually be
# pulled — `aipc models sync` handles this; a missing pull here means every
# request to the alias 404s until someone runs it.
downloaded=$(podman exec lemonade /opt/lemonade/lemonade list --downloaded 2>/dev/null)
printf '%s\n' "$downloaded" | grep -q "gemma4-it-e4b-FLM" \
  || fail "llm-lemonade: gemma4-it-e4b-FLM not pulled — run 'aipc models sync'"
printf '%s\n' "$downloaded" | grep -q "Gemma-4-26B-A4B-it-GGUF" \
  || fail "llm-lemonade: Gemma-4-26B-A4B-it-GGUF (coder-agentic) not pulled — run 'aipc models sync'"
printf '%s\n' "$downloaded" | grep -q "Ornith-1.0-35B-GGUF-Q4_K_M" \
  || fail "llm-lemonade: Ornith-1.0-35B-GGUF-Q4_K_M (ornith-35b) not pulled — run 'aipc models sync'"

# llamacpp:vulkan backend must be installed — hardware-verified 2026-07-05
# to be the fastest backend on this hardware for coder-agentic/ornith-35b
# (see README). Checked by binary presence, not `lemonade backends`' status
# column — that command doesn't mark vulkan "installed" even right after a
# successful `lemonade load --llamacpp vulkan` auto-installed it (verified
# 2026-07-05: binary present and working, status column still said
# "installable"). A missing binary here means the first chat request to
# either alias pays a ~220MB download before it can respond.
podman exec lemonade test -x /root/.cache/lemonade/bin/llamacpp/vulkan/llama-server \
  || fail "llm-lemonade: llamacpp:vulkan backend not installed — run 'podman exec lemonade /opt/lemonade/lemonade backends install llamacpp:vulkan'"

# config.json must have the merged settings lemonade.service's ExecStartPre
# applies — on a fresh first boot the file may not exist until lemond's
# first run, in which case this fails once and clears on the next restart.
config_json=$(podman exec lemonade cat /root/.cache/lemonade/config.json 2>/dev/null || echo '{}')
printf '%s' "$config_json" | grep -q '"max_loaded_models": *2' \
  || fail "llm-lemonade: config.json max_loaded_models != 2 — restart lemonade.service to reapply, or check jq is installed"
printf '%s' "$config_json" | grep -q '"enable_dgpu_gtt": *true' \
  || fail "llm-lemonade: config.json enable_dgpu_gtt != true — restart lemonade.service to reapply, or check jq is installed"
