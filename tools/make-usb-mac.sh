#!/bin/bash
# make-usb-mac.sh — write the verified Bazzite ISO to a USB stick from macOS.
# Usage: bash tools/make-usb-mac.sh [path/to/bazzite-stable-amd64.iso]
set -eu

ISO="${1:-$HOME/Downloads/aipc-install/bazzite-stable-amd64.iso}"
CHECKSUM_FILE="${ISO}-CHECKSUM"

[ -f "$ISO" ] || { echo "ERROR: ISO not found: $ISO" >&2; exit 1; }
[ -f "$CHECKSUM_FILE" ] || { echo "ERROR: checksum file not found: $CHECKSUM_FILE" >&2; exit 1; }

echo "Verifying SHA-256 (takes a minute for ~8 GB)..."
actual=$(shasum -a 256 "$ISO" | awk '{print $1}')
expected=$(awk '{print $1}' "$CHECKSUM_FILE")
if [ "$actual" != "$expected" ]; then
    echo "ERROR: SHA-256 mismatch — do not write this ISO." >&2
    echo "  got:  $actual" >&2
    echo "  want: $expected" >&2
    exit 1
fi
echo "Checksum OK: $actual"
echo ""

echo "External disks:"
diskutil list external physical
echo ""
read -rp "Target disk number (e.g. 4 for /dev/disk4) — ALL DATA ON IT WILL BE ERASED: " disknum
[ -n "$disknum" ] || { echo "ERROR: no disk number given" >&2; exit 1; }
DISK="/dev/disk${disknum}"
RDISK="/dev/rdisk${disknum}"

diskutil info "$DISK" >/dev/null || { echo "ERROR: $DISK not found" >&2; exit 1; }
internal=$(diskutil info "$DISK" | awk -F: '/Internal/{gsub(/ /,"",$2); print $2; exit}')
if [ "$internal" = "Yes" ]; then
    echo "ERROR: $DISK is an INTERNAL disk — refusing." >&2
    exit 1
fi

size_bytes=$(diskutil info "$DISK" | grep -oE '\(([0-9]+) Bytes\)' | grep -oE '[0-9]+' | head -1)
iso_bytes=$(stat -f%z "$ISO")
if [ -n "$size_bytes" ] && [ "$size_bytes" -lt "$iso_bytes" ]; then
    echo "ERROR: $DISK ($size_bytes bytes) is smaller than the ISO ($iso_bytes bytes)." >&2
    exit 1
fi

echo ""
diskutil info "$DISK" | grep -E 'Device Node|Media Name|Disk Size'
read -rp "Type the disk node again to confirm (${DISK}): " confirm
[ "$confirm" = "$DISK" ] || { echo "Aborted: confirmation mismatch." >&2; exit 1; }

echo "Unmounting ${DISK}..."
diskutil unmountDisk "$DISK"
echo "Writing ISO with dd (needs sudo; ~10-20 min, Ctrl+T shows progress)..."
sudo dd if="$ISO" of="$RDISK" bs=4m status=progress
sync
diskutil eject "$DISK" || true
echo ""
echo "Done. Label the stick, plug it into the AI PC, boot via F12/F1 one-time menu."
