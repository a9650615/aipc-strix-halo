#!/bin/sh
# post-install.sh — agent-tools-usage
# BUILD-TIME ONLY. Library only; no daemon, no systemctl --now.
set -eu

# Package is delivered via files/ → /usr/lib/aipc-agent/aipc_agent_tools_usage.
# agent-orchestrator post-install writes aipc-agent.pth so the venv can import it.
echo "agent-tools-usage: library installed under /usr/lib/aipc-agent"
