#!/bin/sh
# verify.sh — llm-ollama
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# Quadlet service is active
systemctl is-active --quiet ollama.service \
  || fail "llm-ollama: ollama.service not active"

# API responds on the expected port
port=$(cat /etc/aipc/env.d/llm-ollama/port 2>/dev/null || echo "11434")
curl -fsS "http://127.0.0.1:${port}/api/tags" >/dev/null 2>&1 \
  || fail "llm-ollama: API not responding on 127.0.0.1:${port}"

# At least one model is pulled
curl -fsS "http://127.0.0.1:${port}/api/tags" | grep -q '"models"' \
  || fail "llm-ollama: no models loaded"
