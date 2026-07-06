#!/bin/sh
# Static checks only (§9): pure-stdlib library, no daemon to hardware-verify.
# Exit 0 = pass, non-zero = fail with one-line stderr.
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
pkg_dir="$this_dir/files/usr/lib/aipc-agent"

fail() { echo "agent-tools-files: $*" >&2; exit 1; }

[ -f "$pkg_dir/aipc_agent_tools_files/tools.py" ] || fail "tools.py missing"
python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_agent_tools_files/tools.py').read())" \
    || fail "syntax error in tools.py"
PYTHONPATH="$pkg_dir" python3 -c "from aipc_agent_tools_files.tools import self_test; self_test()" \
    >/dev/null || fail "self-test failed (allowlist/traversal/gate fail-closed)"

echo "agent-tools-files: static + self-test OK (render-verified; not hardware-verified — no runtime service)"
