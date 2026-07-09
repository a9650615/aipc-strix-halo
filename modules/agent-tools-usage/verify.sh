#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
pkg_dir="$this_dir/files/usr/lib/aipc-agent"

fail() { echo "agent-tools-usage: $*" >&2; exit 1; }

[ -f "$pkg_dir/aipc_agent_tools_usage/usage.py" ] || fail "usage.py missing"
python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_agent_tools_usage/usage.py').read())" \
    || fail "syntax error in usage.py"
PYTHONPATH="$pkg_dir" python3 -c "from aipc_agent_tools_usage.usage import self_test; self_test()" \
    || fail "self-test failed"

echo "agent-tools-usage: static + self-test OK (render-verified; assistant wiring needs live /chat)"
