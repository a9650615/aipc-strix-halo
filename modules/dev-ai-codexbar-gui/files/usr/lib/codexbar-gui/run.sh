#!/bin/bash
# Dev-tree launcher (no hardcoded user paths).
set -eu

PORT="${1:-8080}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${ROOT}/../../../../.." && pwd)"
USAGE_ROOT="${REPO_ROOT}/modules/dev-ai-codexbar-usage/files/usr/lib/aipc-codexbar-usage"
GUI_ROOT="${ROOT}"

export PYTHONPATH="${GUI_ROOT}:${USAGE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    python3 -m codexbar_usage serve --port "${PORT}" &
    sleep 1
fi

exec python3 -m codexbar_gui --port "${PORT}"
