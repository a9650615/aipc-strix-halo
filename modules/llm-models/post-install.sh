#!/bin/sh
# post-install.sh — llm-models
# Build-time: models.yaml is already staged at /etc/aipc/models/models.yaml
# by the renderer's `COPY modules/llm-models/files/ /` step — nothing to
# copy here. Only an optional consistency check if the aipc CLI is present.
set -eu

if command -v aipc >/dev/null 2>&1; then
  aipc models sync --check || true
fi
