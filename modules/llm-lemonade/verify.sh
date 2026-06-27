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

# Quadlet service is active
systemctl is-active --quiet lemonade.service \
  || fail "llm-lemonade: lemonade.service not active"

# API responds
port=$(cat /etc/aipc/env.d/llm-lemonade/port 2>/dev/null || echo "8000")
curl -fsS "http://127.0.0.1:${port}/health" >/dev/null 2>&1 \
  || fail "llm-lemonade: API not responding on 127.0.0.1:${port}"
