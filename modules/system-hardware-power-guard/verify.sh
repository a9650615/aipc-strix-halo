#!/bin/bash
# verify.sh for system-hardware-power-guard
# Static + live-read checks (CLAUDE.md §9). Render-verified, NOT
# hardware-verified until a real back-feed event is observed on the AI PC.
# Exit 0 = pass, 2 = intentionally disabled/optional, other non-zero = fail.
set -euo pipefail

MOD="modules/system-hardware-power-guard"
PY="$MOD/files/usr/lib/aipc-power-guard/power_guard.py"

fail() { echo "power-guard verify FAIL: $*" >&2; exit 1; }

# 1. Syntax + self-test (reads live sysfs; safe, no writes).
python3 -c "import ast; ast.parse(open('$PY').read())" || fail "python syntax"
python3 "$PY" --self-test || fail "self-test (live sysfs read)"

# 2. Config parses.
python3 -c "import yaml,sys; yaml.safe_load(open('$MOD/files/etc/aipc/power-guard/config.yaml'))" \
  || fail "config.yaml parse"

# 3. Service unit has the kill switch + runs on host (not a container).
grep -q 'ConditionPathExists=!/etc/aipc/power-guard.disabled' \
  "$MOD/files/etc/systemd/system/power-guard.service" \
  || fail "missing ConditionPathExists kill switch"
grep -q 'ExecStart=/usr/bin/python3' \
  "$MOD/files/etc/systemd/system/power-guard.service" \
  || fail "must run as host python, not a container"

# 4. No leftover quadlet container (host service is the correct shape).
[ ! -f "$MOD/files/quadlet/power-guard.container" ] \
  || fail "quadlet container removed — daemon must run on host for sysfs writes"

# .disabled marker present → module is render-verified but not yet enabled.
if [ -f "$MOD/.disabled" ]; then
  echo "power-guard verify OK (render-verified; module .disabled until hardware-verified)"
  exit 2
fi

echo "power-guard verify OK (render-verified + enabled)"
