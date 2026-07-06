#!/bin/sh
# verify.sh — system-asus-input
set -eu

this_dir="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$this_dir" ]; then
    echo "Error: modules/system-asus-input directory not found." >&2
    exit 1
fi

if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$DR_DIR"): disabled (optional)" >&2
    exit 2
fi

# Verify udev rule exists
if [ ! -f "$this_dir/files/etc/udev/rules.d/70-asus-keyboard.rules" ]; then
    echo "Error: udev rule missing." >&2
    exit 1
fi

exit 0
