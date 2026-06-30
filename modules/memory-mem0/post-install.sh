#!/bin/sh
# post-install.sh — memory-mem0
# Build-time only. The mem0 container starts at runtime via its quadlet
# (After=postgres.service llm-litellm.service, Requires=postgres.service)
# and self-initializes its schema via DATABASE_URL. Health readiness is
# checked by verify.sh at verify time — not probed here (nothing listens
# at image-build time).
set -eu

systemctl enable mem0.service
