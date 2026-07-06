#!/bin/sh
# Static checks only (§9): syntax + fail-closed self-tests for gate/input/vlm.
# kdotool-based window-class detection and real input injection are NOT
# exercised here — see README "Verification tiers" for why. Exit 0 = pass,
# non-zero = fail with one-line stderr, 2 = disabled (optional).
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

pkg_dir="$this_dir/files/usr/lib/aipc-agent"
pkg="$pkg_dir/aipc_agent_screen_control"

fail() { echo "agent-screen-control: $*" >&2; exit 1; }

[ -f "$pkg/gate.py" ] && [ -f "$pkg/input.py" ] && [ -f "$pkg/vlm.py" ] && [ -f "$pkg/window.py" ] \
    || fail "package files missing"
[ -f "$this_dir/files/etc/aipc/agent-gate/screen-blacklist.conf" ] \
    || fail "screen-blacklist.conf missing"

for f in "$pkg"/*.py; do
    python3 -c "import ast; ast.parse(open('$f').read())" || fail "syntax error in $f"
done

PYTHONPATH="$pkg_dir" python3 -c "from aipc_agent_screen_control.input import self_test; self_test()" \
    >/dev/null || fail "input self-test failed (expected fail-closed with no gate socket)"
PYTHONPATH="$pkg_dir" python3 -c "from aipc_agent_screen_control.vlm import self_test; self_test()" \
    >/dev/null || fail "vlm self-test failed (expected fail-closed with no gate socket)"

echo "agent-screen-control: static + fail-closed self-tests OK (render-verified; window-class detection and real input injection are NOT hardware-verified here, see README)"
