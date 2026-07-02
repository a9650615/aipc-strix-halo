#!/bin/bash
# Thin wrapper for curl | bash usage:
#   curl -fsSL https://raw.githubusercontent.com/a9650615/aipc-strix-halo/main/tools/bootstrap.sh | bash
# Delegates to the single entry point with --direct flag (skip guided menu).
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$REPO_ROOT/install-aipc-linux.sh" ]; then
    exec bash "$REPO_ROOT/install-aipc-linux.sh" --direct "$@"
else
    echo "ERROR: install-aipc-linux.sh not found at $REPO_ROOT" >&2
    echo "Clone the full repo first: git clone https://github.com/a9650615/aipc-strix-halo" >&2
    exit 1
fi
