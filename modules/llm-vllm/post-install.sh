#!/bin/sh
# post-install.sh — llm-vllm
# Build-time: nothing to do. This backend is optional/on-demand (per README);
# the quadlet has no [Install] section, so it never auto-starts at boot.
# `systemctl enable --now vllm.service` (build has no running init, and no
# guaranteed network for the model download either) is a runtime admin
# action, not something a build step can do.
set -eu
