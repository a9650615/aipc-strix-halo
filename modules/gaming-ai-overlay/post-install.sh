#!/bin/sh
# post-install.sh — gaming-ai-overlay
# Build-time only: install config stub.
set -eu

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/etc/aipc/gaming/overlay.yaml" \
    /etc/aipc/gaming/overlay.yaml
