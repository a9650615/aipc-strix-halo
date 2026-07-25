#!/bin/bash
# Dev-tree / live-hotfix launcher — tray GUI; official codexbar on PATH.
# Prefers repo tree (this script's dir) over /usr/lib/codexbar-gui.
set -eu
PORT="${1:-8080}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
# Optional extra prepend (same env as codexbar-gui-web.service)
if [ -n "${CODEXBAR_GUI_SRC:-}" ]; then
  export PYTHONPATH="${CODEXBAR_GUI_SRC}:${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
else
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
fi
export PATH="${HOME}/.local/bin:/usr/lib/aipc/tools/.venv/bin:${PATH}"

if ! command -v codexbar >/dev/null 2>&1; then
    echo "Install official codexbar CLI first (releases on steipete/CodexBar)." >&2
    exit 1
fi

if [ -x /usr/lib/aipc/tools/.venv/bin/python ]; then
  PY=/usr/lib/aipc/tools/.venv/bin/python
else
  PY=python3
fi

exec "$PY" -m codexbar_gui --port "${PORT}"
