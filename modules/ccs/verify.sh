#!/bin/sh
# verify.sh — ccs
set -eu

this_dir="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$this_dir" ]; then
    echo "Error: modules/ccs directory not found." >&2
    exit 1
fi

if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

exit 0
