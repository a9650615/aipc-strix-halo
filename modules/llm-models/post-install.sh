#!/bin/sh
# post-install.sh — llm-models
# Idempotent: safe to re-run on image rebuilds.
set -eu

src=$(dirname "$0")/files/etc/aipc/models/models.yaml
dst=/etc/aipc/models/models.yaml

mkdir -p /etc/aipc/models
install -m 0644 "${src}" "${dst}"

if command -v aipc >/dev/null 2>&1; then
  aipc models sync --check || true
fi
