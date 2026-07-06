#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

# Basic-skeleton scope: supervisor + daily_assistant (task 2.6) exist; this
# checks both construct (daily_assistant is imported by graphs.py, so
# supervisor() transitively exercises it), not the full spec's "all four
# sub-agent graphs constructible" scenario.
/usr/lib/aipc-agent/venv/bin/python3 -c "from aipc_agent.graphs import supervisor; supervisor()" || {
    echo "agent-orchestrator: supervisor graph failed to construct" >&2
    exit 1
}

systemctl is-active --quiet aipc-agent-orchestrator.service || {
    echo "agent-orchestrator: aipc-agent-orchestrator.service not active" >&2
    exit 1
}

curl -sf -o /dev/null -X POST http://127.0.0.1:4100/chat \
    -H "Content-Type: application/json" \
    -d '{"text": "ping"}' || {
    echo "agent-orchestrator: POST /chat did not return 2xx" >&2
    exit 1
}

exit 0
