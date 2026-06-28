#!/bin/sh
# post-install.sh — llm-ollama
# Idempotent: safe to re-run on image rebuilds.
set -eu

model_dir=/var/lib/aipc-models
if command -v btrfs >/dev/null 2>&1 && btrfs subvolume show / >/dev/null 2>&1; then
  if [ ! -d "$model_dir" ]; then
    btrfs subvolume create "$model_dir" 2>/dev/null || mkdir -p "$model_dir"
  fi
else
  mkdir -p "$model_dir"
fi

systemctl enable --now ollama.service

endpoint=http://127.0.0.1:11434
default_model=qwen2.5:7b-instruct-q4_K_M

for _i in $(seq 1 30); do
  curl -fsS "$endpoint/api/tags" >/dev/null 2>&1 && break
  sleep 1
done

if ! curl -fsS "$endpoint/api/tags" | grep -q '"name"'; then
  curl -fsS -X POST "$endpoint/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$default_model\"}" >/dev/null
fi
