#!/bin/bash
# Thin wrapper for curl | bash usage:
#   curl -fsSL https://raw.githubusercontent.com/a9650615/aipc-strix-halo/main/tools/bootstrap.sh | bash
# Delegates to the single entry point with --direct flag (skip guided menu).
set -eu

# BASH_SOURCE is unset when piped via curl | bash; fall back to cwd probing.
if [ -n "${BASH_SOURCE:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    REPO_ROOT="$(pwd)"
fi

if [ -f "$REPO_ROOT/install-aipc-linux.sh" ]; then
    exec bash "$REPO_ROOT/install-aipc-linux.sh" --direct "$@"
fi

# curl | bash with no local checkout: fetch the entry point from the repo
ENTRY_URL="https://raw.githubusercontent.com/a9650615/aipc-strix-halo/main/install-aipc-linux.sh"
TMP_ENTRY="$(mktemp /tmp/install-aipc-linux.XXXXXX.sh)"
trap 'rm -f "$TMP_ENTRY"' EXIT
if curl -fsSL "$ENTRY_URL" -o "$TMP_ENTRY"; then
    bash "$TMP_ENTRY" --direct "$@"
else
    echo "ERROR: could not fetch install-aipc-linux.sh from $ENTRY_URL" >&2
    echo "Clone the full repo instead: git clone https://github.com/a9650615/aipc-strix-halo" >&2
    exit 1
fi
