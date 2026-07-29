#!/bin/bash
# verify.sh for system-hardware-power-guard / aipc-power-agent
set -euo pipefail

MOD="modules/system-hardware-power-guard"
AGENT="$MOD/files/usr/lib/aipc-power-agent/agent.py"
UNIT="$MOD/files/etc/systemd/system/aipc-power-agent.service"
CFG="$MOD/files/etc/aipc/power-agent/config.yaml"

fail() { echo "aipc-power-agent verify FAIL: $*" >&2; exit 1; }

python3 -c "import ast; ast.parse(open('$AGENT').read())" || fail "agent.py syntax"
python3 -c "import ast; ast.parse(open('$MOD/files/usr/lib/aipc-power-agent/backfeed.py').read())" || fail "backfeed.py syntax"
python3 -c "import ast; ast.parse(open('$MOD/files/usr/lib/aipc-power-agent/core_parking.py').read())" || fail "core_parking.py syntax"
python3 "$AGENT" --self-test || fail "self-test (live sysfs read)"

python3 -c "import yaml; yaml.safe_load(open('$CFG'))" || fail "config.yaml parse"

grep -q 'ConditionPathExists=!/etc/aipc/power-agent.disabled' "$UNIT" \
  || fail "missing ConditionPathExists kill switch"
grep -q 'ExecStart=/usr/bin/python3 /usr/lib/aipc-power-agent/agent.py' "$UNIT" \
  || fail "ExecStart must run host agent.py"
grep -q 'Alias=power-guard.service' "$UNIT" \
  || fail "missing transitional Alias=power-guard.service"

# Must not ship the old separate usbc unit from this module.
[ ! -f "$MOD/files/etc/systemd/system/aipc-usbc-core-policy.service" ] \
  || fail "usbc-core-policy unit must not be shipped; absorbed into agent"
[ ! -f "$MOD/files/etc/systemd/system/power-guard.service" ] \
  || fail "power-guard.service file must not be shipped; use Alias on aipc-power-agent"

if [ -f "$MOD/.disabled" ]; then
  echo "aipc-power-agent verify OK (render-verified; module .disabled)"
  exit 2
fi

echo "aipc-power-agent verify OK (render-verified + enabled)"
