#!/bin/bash
# verify.sh for system-suspend-gpu-guard
# Static checks only here (CLAUDE.md §9). The busy-detection/inhibitor-lock
# mechanism has been separately hardware-verified via manual systemd-inhibit
# --list checks on the physical AI PC — see README.md's verification note.
set -euo pipefail

MOD="modules/system-suspend-gpu-guard"
SH="$MOD/files/usr/lib/aipc-suspend-gpu-guard/guard.sh"
UNIT="$MOD/files/etc/systemd/system/suspend-gpu-guard.service"

fail() { echo "suspend-gpu-guard verify FAIL: $*" >&2; exit 1; }

bash -n "$SH" || fail "guard.sh syntax"

grep -q 'ConditionPathExists=!/etc/aipc/suspend-gpu-guard.disabled' "$UNIT" \
  || fail "missing kill-switch ConditionPathExists"
grep -q 'systemd-inhibit' "$SH" || fail "guard.sh must use systemd-inhibit"
grep -q -- '--mode=block' "$SH" || fail "must use block mode, not delay"
grep -q 'AC0/online' "$SH" || fail "must gate the block on AC power"

echo "suspend-gpu-guard verify OK (static)"
