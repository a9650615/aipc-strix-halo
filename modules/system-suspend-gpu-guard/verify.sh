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
grep -q 'AC0/online\|AC_ONLINE_PATH' "$SH" || fail "must gate the block on AC power"
grep -q 'IDLE_STREAK_NEED' "$SH" || fail "must hysteresis-release (IDLE_STREAK_NEED)"
grep -q 'BUSY_THRESHOLD' "$SH" || fail "must expose BUSY_THRESHOLD"
# Default threshold must clear ambient desktop/always-on LLM load (~10–30%).
grep -qE 'BUSY_THRESHOLD:-50|BUSY_THRESHOLD=50' "$SH" \
  || fail "default BUSY_THRESHOLD should be >=50 (was 15 — stuck inhibitor on ambient load)"

JOURNAL_CONF="$MOD/files/etc/systemd/journald.conf.d/90-suspend-hang-forensics.conf"
[ -f "$JOURNAL_CONF" ] || fail "missing journald forensics drop-in"
grep -q '^RuntimeMaxUse=' "$JOURNAL_CONF" || fail "journald drop-in missing RuntimeMaxUse"
grep -q '^RateLimitBurst=' "$JOURNAL_CONF" || fail "journald drop-in missing RateLimitBurst"

echo "suspend-gpu-guard verify OK (static)"
