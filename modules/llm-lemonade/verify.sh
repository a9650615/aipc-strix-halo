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

# resident-small (FLM/NPU) must actually be pulled — `aipc models sync`
# handles this; a missing pull here means every request to the alias
# 404s until someone runs it.
podman exec lemonade /opt/lemonade/lemonade list --downloaded 2>/dev/null | grep -q "gemma4-it-e4b-FLM" \
  || fail "llm-lemonade: gemma4-it-e4b-FLM not pulled — run 'aipc models sync'"
