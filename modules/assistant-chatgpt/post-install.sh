#!/bin/bash
set -euo pipefail

# Build-time: dirs only. Playwright browser download is large — prefer
# first-boot or verify path; do not block image build on network.
install -d /var/lib/aipc-chatgpt
install -d /usr/lib/aipc_chatgpt

# If pip/playwright already present in the image, try chromium install once
# (best-effort, non-fatal for offline builds).
if command -v python3 >/dev/null 2>&1; then
  if python3 -c "import playwright" 2>/dev/null; then
    python3 -m playwright install chromium >/tmp/aipc-chatgpt-playwright.log 2>&1 || true
  fi
fi
