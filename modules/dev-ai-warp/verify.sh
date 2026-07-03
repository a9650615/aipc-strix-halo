#!/bin/sh
# verify.sh — dev-ai-warp
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi
command -v warp-terminal >/dev/null 2>&1 \
    || { echo "dev-ai-warp: warp-terminal not on PATH" >&2; exit 1; }
exit 0
