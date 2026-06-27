#!/bin/sh
# verify.sh — llm-vllm
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
# Exit code 2 = service not enabled (expected, module is optional).
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# Optional module — if service is disabled, that's fine
if ! systemctl is-enabled --quiet vllm.service 2>/dev/null; then
  exit 0
fi

# If enabled, it must be active
systemctl is-active --quiet vllm.service \
  || fail "llm-vllm: vllm.service enabled but not active"

# API responds
port=$(cat /etc/aipc/env.d/llm-vllm/port 2>/dev/null || echo "8001")
curl -fsS "http://127.0.0.1:${port}/health" >/dev/null 2>&1 \
  || fail "llm-vllm: API not responding on 127.0.0.1:${port}"
