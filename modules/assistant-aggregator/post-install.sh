#!/bin/bash
set -euo pipefail

# Build-time only: install paths; no live services (CLAUDE.md §8).
install -d /etc/aipc/assistant
install -d /usr/lib/aipc_assistant
install -d /var/lib/aipc-assistant

# Default mode local if missing (idempotent).
if [ ! -f /etc/aipc/assistant/mode ]; then
  printf 'local\n' >/etc/aipc/assistant/mode
fi
