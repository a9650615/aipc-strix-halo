#!/bin/bash
# CodexBar GUI — official CLI only. Default port 8080 (NOT 8000).
set -eu

PORT="${CODEXBAR_PORT:-8080}"
GUI_ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${GUI_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export PATH="${HOME}/.local/bin:${PATH}"

if ! python3 -c "import PySide6" 2>/dev/null; then
    echo "ERROR: PySide6 not installed" >&2
    exit 1
fi

if ! command -v codexbar >/dev/null 2>&1; then
    echo "ERROR: official codexbar CLI not on PATH" >&2
    echo "Install: https://github.com/steipete/CodexBar/releases" >&2
    exit 1
fi

# Refuse to treat fake Python aipc-usage as healthy.
health_json="$(curl -sf "http://127.0.0.1:${PORT}/health" 2>/dev/null || true)"
if echo "$health_json" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    if echo "$health_json" | grep -qE '"version"[[:space:]]*:[[:space:]]*"0\.1'; then
        echo "WARN: :${PORT} is aipc-usage Python port (fake data), not official codexbar." >&2
        echo "  Kill it, e.g.:  pkill -f 'codexbar_usage.cli serve' " >&2
        echo "  GUI will use \`codexbar usage\` CLI instead of HTTP." >&2
    elif ! echo "$health_json" | grep -q '"version"'; then
        :
    else
        echo "Official-looking serve already on :${PORT}"
    fi
else
    if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
        echo "WARN: :${PORT} in use but /health is not official codexbar." >&2
        echo "  GUI will call CLI directly. Free the port to use serve." >&2
    else
        echo "Starting official codexbar serve on 127.0.0.1:${PORT} ..."
        codexbar serve --port "${PORT}" &
        for _ in $(seq 1 40); do
            h="$(curl -sf "http://127.0.0.1:${PORT}/health" 2>/dev/null || true)"
            if echo "$h" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' \
                && ! echo "$h" | grep -qE '"version"[[:space:]]*:[[:space:]]*"0\.1'; then
                echo "serve ready"
                break
            fi
            sleep 0.25
        done
    fi
fi

exec python3 -m codexbar_gui --port "${PORT}" "$@"
