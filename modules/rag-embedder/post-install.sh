#!/bin/sh
set -eu

systemctl enable --now rag-embedder.service

for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8201/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:8201/healthz >/dev/null 2>&1; then
  echo "rag-embedder: /healthz not ready after 60s (first-run may still be downloading models)" >&2
  exit 1
fi
