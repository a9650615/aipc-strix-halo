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

# If the manifest requests mlock for any model, the container must actually
# hold CAP_IPC_LOCK — otherwise LLAMA_ARG_MLOCK=1 is set but silently fails
# to lock anything (hardware-verified 2026-07-04: without the capability,
# mlock() on the resident weights never succeeds, though llama-server
# doesn't treat that as fatal, so nothing else here would catch it).
if grep -q 'mlock: *true' /etc/aipc/models/models.yaml 2>/dev/null; then
  podman inspect ollama --format '{{.EffectiveCaps}}' 2>/dev/null | grep -q CAP_IPC_LOCK \
    || fail "llm-ollama: models.yaml requests mlock but ollama container lacks CAP_IPC_LOCK"
fi
