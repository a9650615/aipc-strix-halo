#!/bin/bash
# Dev-tree launcher — GUI only; requires official codexbar on PATH.
set -eu
PORT="${1:-8080}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v codexbar >/dev/null 2>&1; then
    echo "Install official codexbar CLI first (releases on steipete/CodexBar)." >&2
    exit 1
fi

exec python3 -m codexbar_gui --port "${PORT}"
