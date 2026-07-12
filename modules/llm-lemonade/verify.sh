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
printf '%s\n' "$downloaded" | grep -q "qwen3.5-4b-FLM" \
  || fail "llm-lemonade: qwen3.5-4b-FLM not pulled — run 'aipc models sync'"
printf '%s\n' "$downloaded" | grep -q "Gemma-4-26B-A4B-it-GGUF" \
  || fail "llm-lemonade: Gemma-4-26B-A4B-it-GGUF (coder-agentic) not pulled — run 'aipc models sync'"
printf '%s\n' "$downloaded" | grep -q "Ornith-1.0-35B-MTP-APEX-I-Balanced" \
  || fail "llm-lemonade: Ornith-1.0-35B-MTP-APEX-I-Balanced (ornith-35b) not pulled — run 'aipc models sync'"
printf '%s\n' "$downloaded" | grep -q "Qwen3.5-122B-A10B-Uncensored-APEX-Compact" \
  || fail "llm-lemonade: Qwen3.5-122B-A10B-Uncensored-APEX-Compact (coder-122b) not pulled — run 'aipc models sync'"

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
# Expect a generous slot budget (memory-rich box keeps multiple LLMs resident).
printf '%s' "$config_json" | grep -qE '"max_loaded_models": *([3-9]|[1-9][0-9]+)' \
  || fail "llm-lemonade: config.json max_loaded_models too low — restart lemonade.service to reapply"

# Also check the live health endpoint directly — config.json alone doesn't
# prove the running lemond process actually picked the value up (a stale
# pre-fix copy of configure-lemonade.sh deployed under /usr/lib/aipc/...
# would leave config.json correct-looking while the server itself never
# re-ran ExecStartPre with it — see docs/live-hotfix-workflow.md). 10.8.1
# hardware-verified 2026-07-11: `/api/v1/health`'s `max_models.llm` mirrors
# `max_loaded_models` directly, no separate per-type key exists.
health_json=$(curl -fsS "http://127.0.0.1:${port}/api/v1/health" 2>/dev/null || echo '{}')
printf '%s' "$health_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
sys.exit(0 if d.get('max_models', {}).get('llm', 0) >= 3 else 1)
" || fail "llm-lemonade: /api/v1/health max_models.llm < 3 — restart lemonade.service to reapply config.json"
# ensure-resident-small must be installed (pin path for always-on FLM)
[ -x /usr/lib/aipc/llm-lemonade/ensure-resident-small.sh ] \
  || [ -x /etc/aipc/llm-lemonade/ensure-resident-small.sh ] \
  || [ -x /var/lib/aipc-lemonade/ensure-resident-small.sh ] \
  || fail "llm-lemonade: ensure-resident-small.sh missing"

[ -x /usr/lib/aipc/llm-lemonade/lemonade-idle-release.py ] \
  || [ -x /etc/aipc/llm-lemonade/lemonade-idle-release.py ] \
  || fail "llm-lemonade: lemonade-idle-release.py missing"
idle_release=/usr/lib/aipc/llm-lemonade/lemonade-idle-release.py
[ -x "${idle_release}" ] || idle_release=/etc/aipc/llm-lemonade/lemonade-idle-release.py
python3 "${idle_release}" --self-test >/dev/null \
  || fail "llm-lemonade: lemonade-idle-release.py self-test failed"
systemctl is-enabled --quiet aipc-lemonade-idle-release.timer \
  || fail "llm-lemonade: aipc-lemonade-idle-release.timer not enabled"

printf '%s' "$config_json" | grep -q '"enable_dgpu_gtt": *true' \
  || fail "llm-lemonade: config.json enable_dgpu_gtt != true — restart lemonade.service to reapply, or check jq is installed"

# coder-agentic/ornith-35b must be saved with -np 4 -kvu (see README's
# "Concurrency" section) — without kv-unified, an explicit -np statically
# divides the context budget per slot, and Claude Code's system prompt
# (36.8k-56k tokens, hardware-verified 2026-07-05) blows past a divided
# per-slot cap with a context_length_exceeded 400. This is a saved
# per-model load option, not a config.json key, so it doesn't self-heal on
# restart — a missing entry here means someone needs to re-run the
# `lemonade load ... --llamacpp-args "-np 4 -kvu" --save-options` command
# from the README for that model. (Check below only greps for "-np"/"-kvu"
# substrings, not the specific slot count, so it doesn't need updating
# every time the slot count is retuned.)
recipe_options=$(podman exec lemonade cat /root/.cache/lemonade/recipe_options.json 2>/dev/null || echo '{}')
printf '%s' "$recipe_options" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for key in ('builtin.Gemma-4-26B-A4B-it-GGUF', 'user.Ornith-1.0-35B-MTP-APEX-I-Balanced'):
    args = d.get(key, {}).get('llamacpp_args', '')
    if '-np' not in args or '-kvu' not in args:
        sys.exit(1)
" 2>/dev/null || fail "llm-lemonade: recipe_options.json missing -np/-kvu for coder-agentic/ornith-35b — see README's Concurrency section"
