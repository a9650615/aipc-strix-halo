#!/bin/sh
# post-install.sh — game-strategy-rag
# Build-time: create runtime ingest cache directory.
set -eu

mkdir -p /var/lib/aipc/game-strategy
