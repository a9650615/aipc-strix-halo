#!/bin/sh
# post-install.sh — rag-embedder
# Build-time only. The embedder container starts at runtime via its quadlet
# and self-initializes (model download happens inside the container on first
# start). Health readiness is checked by verify.sh at verify time — not probed
# here (nothing listens at image-build time).
set -eu

systemctl enable rag-embedder.service
