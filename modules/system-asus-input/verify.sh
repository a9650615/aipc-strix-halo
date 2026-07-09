#!/bin/sh
# verify.sh — system-asus-input
set -eu

this_dir="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$this_dir" ]; then
    echo "Error: modules/system-asus-input directory not found." >&2
    exit 1
fi

if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

rule_path="$this_dir/files/etc/udev/rules.d/70-asus-keyboard.rules"
hwdb_path="$this_dir/files/etc/udev/hwdb.d/90-aipc-asus-side-button.hwdb"
discovery_path="$this_dir/files/usr/bin/aipc-asus-side-button-discover"
post_install_path="$this_dir/post-install.sh"

if [ ! -f "$rule_path" ]; then
    echo "Error: udev rule missing." >&2
    exit 1
fi

if [ ! -f "$hwdb_path" ]; then
    echo "Error: hwdb template missing." >&2
    exit 1
fi

if [ ! -x "$discovery_path" ]; then
    echo "Error: discovery helper missing or not executable." >&2
    exit 1
fi

python3 "$discovery_path" --self-test

if grep -Eq 'modprobe|udevadm|systemctl|aipc-voice' "$post_install_path"; then
    echo "Error: post-install.sh contains forbidden runtime actions." >&2
    exit 1
fi

exit 0
