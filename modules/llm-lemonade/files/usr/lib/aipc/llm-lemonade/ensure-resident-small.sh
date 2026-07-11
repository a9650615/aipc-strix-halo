#!/bin/sh
# ensure-resident-small.sh — keep the always-on NPU chat model loaded + pinned.
#
# Root cause (hardware 2026-07-10): Lemonade counts FLM (gemma4-it-e4b-FLM) in
# the same "llm" LRU pool as Vulkan GGUFs. When max_loaded_models is full, LRU
# evicts FLM:
#   Slot limit reached for type llm, evicting LRU: gemma4-it-e4b-FLM
# Then every resident-small request cold-loads or queues → voice「本地模型连不上」.
#
# Fix (Lemonade multi-model docs): POST /api/v1/load with "pinned": true so the
# model is excluded from LRU eviction. Idempotent; re-run after lemonade restart.
set -eu

BASE="${AIPC_LEMONADE_URL:-http://127.0.0.1:8001}"
MODEL="${AIPC_RESIDENT_MODEL_ID:-gemma4-it-e4b-FLM}"

log() { echo "ensure-resident-small: $*" >&2; }

i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS -m 2 "${BASE}/v1/models" >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
if ! curl -fsS -m 2 "${BASE}/v1/models" >/dev/null 2>&1; then
  log "lemonade not ready at ${BASE}"
  exit 1
fi

# Load with pin (or refresh pin). Cold FLM can take >60s on first boot.
code=$(curl -sS -m 180 -o /tmp/aipc-resident-load.json -w '%{http_code}' \
  -X POST "${BASE}/api/v1/load" \
  -H 'Content-Type: application/json' \
  -d "{\"model_name\":\"${MODEL}\",\"pinned\":true}" || echo 000)

if [ "$code" != "200" ] && [ "$code" != "201" ]; then
  code=$(curl -sS -m 180 -o /tmp/aipc-resident-load.json -w '%{http_code}' \
    -X POST "${BASE}/api/v0/load" \
    -H 'Content-Type: application/json' \
    -d "{\"model_name\":\"${MODEL}\",\"pinned\":true}" || echo 000)
fi
if [ "$code" != "200" ] && [ "$code" != "201" ]; then
  code=$(curl -sS -m 30 -o /tmp/aipc-resident-load.json -w '%{http_code}' \
    -X POST "${BASE}/internal/pin" \
    -H 'Content-Type: application/json' \
    -d "{\"model_name\":\"${MODEL}\"}" || echo 000)
fi

# Do NOT unload other models. This machine has enough unified memory to keep
# big Vulkan LLMs resident; only pin FLM so LRU never evicts the always-on
# chat path. (User: 记忆体够就别砍大模型.)

# Chat prove with retries — load may return before flm-server accepts traffic.
chat_code=000
j=0
while [ "$j" -lt 18 ]; do
  chat_code=$(curl -sS -m 20 -o /tmp/aipc-resident-chat.json -w '%{http_code}' \
    -X POST "${BASE}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":2}" \
    || echo 000)
  if [ "$chat_code" = "200" ]; then
    break
  fi
  j=$((j + 1))
  sleep 3
done

if [ "$chat_code" != "200" ]; then
  log "FAIL load_http=${code} chat_http=${chat_code} model=${MODEL}"
  head -c 400 /tmp/aipc-resident-load.json 2>/dev/null || true
  echo >&2
  head -c 400 /tmp/aipc-resident-chat.json 2>/dev/null || true
  echo >&2
  exit 1
fi

log "OK model=${MODEL} load_http=${code} chat_http=${chat_code} (pinned, always-on)"
exit 0
