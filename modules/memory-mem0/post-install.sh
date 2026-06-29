#!/bin/sh
set -eu

systemctl enable --now mem0.service

for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:7000/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:7000/healthz >/dev/null 2>&1; then
  echo "mem0: /healthz not ready after 30s" >&2
  exit 1
fi
