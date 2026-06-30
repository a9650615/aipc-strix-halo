#!/bin/sh
# post-install.sh — game-strategy-rag
# Build-time: create runtime ingest cache directory and install config stub.
set -eu

mkdir -p /var/lib/aipc/game-strategy

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/etc/aipc/game-strategy/sources.yaml" \
    /etc/aipc/game-strategy/sources.yaml
