#!/bin/sh
# verify.sh — llm-litellm
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# Quadlet service is active
systemctl is-active --quiet litellm.service \
  || fail "llm-litellm: litellm.service not active"

# Health endpoint responds
endpoint=$(cat /etc/aipc/env.d/llm-litellm/endpoint 2>/dev/null || echo "http://127.0.0.1:4000")
curl -fsS "${endpoint}/health" >/dev/null 2>&1 \
  || fail "llm-litellm: health check failed at ${endpoint}"

# Model namespace is populated
curl -fsS "${endpoint}/v1/models" | grep -q '"data"' \
  || fail "llm-litellm: /v1/models returned no models"

# 0012 memory scheduler is wired: hook file present, self-test passes, and
# the shipped config registers the callback. (Runtime effect — preemption /
# hold — is hardware-verified per the 0012 change, not checkable here.)
[ -f /etc/aipc/litellm/scheduler_hook.py ] \
  || fail "llm-litellm: scheduler_hook.py missing from /etc/aipc/litellm"
python3 /etc/aipc/litellm/scheduler_hook.py --self-test >/dev/null 2>&1 \
  || fail "llm-litellm: scheduler_hook.py --self-test failed"
grep -q 'scheduler_hook.scheduler' /etc/aipc/litellm/config.yaml \
  || fail "llm-litellm: config.yaml does not register scheduler_hook callback"
