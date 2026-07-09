#!/bin/bash
# CodexBar GUI — Linux tray shell over official codexbar CLI.
set -eu

PORT="${CODEXBAR_PORT:-8080}"
GUI_ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${GUI_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if ! python3 -c "import PySide6" 2>/dev/null; then
    echo "ERROR: PySide6 not installed (python3-pyside6)" >&2
    exit 1
fi

if ! command -v codexbar >/dev/null 2>&1 && [[ ! -x "${HOME}/.local/bin/codexbar" ]]; then
    echo "ERROR: official codexbar CLI not found." >&2
    echo "Install Linux CLI from https://github.com/steipete/CodexBar/releases" >&2
    echo "This GUI only ports the UI — core logic is upstream." >&2
    exit 1
fi

export PATH="${HOME}/.local/bin:${PATH}"

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Starting official codexbar serve on :${PORT}..."
    codexbar serve --port "${PORT}" &
    for _ in $(seq 1 30); do
        curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 && break
        sleep 0.5
    done
fi

exec python3 -m codexbar_gui --port "${PORT}" "$@"
