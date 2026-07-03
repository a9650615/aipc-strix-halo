#!/bin/sh
# post-install.sh — llm-ollama
# Build-time: enable the resolver unit that points /var/lib/aipc-models at
# the primary user's home at real boot (content under /var during build
# isn't part of the ostree commit, and the target user's home isn't known
# until the deployed machine's first boot anyway — see aipc-models-dir-setup).
# NO systemctl --now (build has no running init) and no model pull (build
# has no guaranteed network); the quadlet's [Install] WantedBy=default.target
# starts ollama.service at real boot, and `aipc models sync` pulls weights
# afterward.
set -eu

chmod 0755 /usr/lib/aipc/aipc-models-dir-setup
systemctl enable aipc-models-dir.service

# mlock env: llama-server (which Ollama spawns per loaded model) reads
# LLAMA_ARG_MLOCK to pin resident weights in RAM instead of letting the OS
# swap/compress them out — see models.yaml's main-70b entry for why. Ollama
# has no per-model mlock knob, so this is daemon-wide once any manifest
# entry requests it. Pure function of the static manifest already staged
# by the renderer's COPY step (no live service needed) — belongs at build
# time, not in aipc-models-dir-setup's runtime resolver.
mkdir -p /etc/aipc/env.d/llm-ollama
if grep -q 'mlock: *true' /etc/aipc/models/models.yaml 2>/dev/null; then
  printf 'LLAMA_ARG_MLOCK=1\n' > /etc/aipc/env.d/llm-ollama/mlock.env
else
  : > /etc/aipc/env.d/llm-ollama/mlock.env
fi
