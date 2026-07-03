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
