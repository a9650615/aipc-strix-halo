#!/bin/bash
# CodexBar GUI launcher (image path). Auto-starts usage server if needed.
set -eu

PORT="${CODEXBAR_PORT:-8080}"
USAGE_ROOT="${CODEXBAR_USAGE_ROOT:-/usr/lib/aipc-codexbar-usage}"
GUI_ROOT="$(cd "$(dirname "$0")" && pwd)"

export PYTHONPATH="${GUI_ROOT}:${USAGE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if ! python3 -c "import PySide6" 2>/dev/null; then
    echo "ERROR: PySide6 not installed" >&2
    exit 1
fi

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Starting usage server on port ${PORT}..."
    if command -v aipc-usage >/dev/null 2>&1; then
        aipc-usage serve --port "${PORT}" &
    else
        python3 -m codexbar_usage serve --port "${PORT}" &
    fi
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
    if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        echo "ERROR: usage server failed to start on port ${PORT}" >&2
        exit 1
    fi
fi

exec python3 -m codexbar_gui --port "${PORT}" "$@"
