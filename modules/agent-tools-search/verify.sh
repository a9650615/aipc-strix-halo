#!/bin/sh
# verify.sh — agent-tools-search
# Exit 0 = pass, 2 = intentionally disabled/optional, other non-zero = fail.
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
pkg_dir="$this_dir/files/usr/lib/aipc-agent"

fail() { echo "agent-tools-search: $*" >&2; exit 1; }

if [ -f "$this_dir/.disabled" ]; then
    echo "agent-tools-search: disabled (optional)" >&2
    exit 2
fi

[ -f "$pkg_dir/aipc_agent_tools_search/search.py" ] || fail "search.py missing"
python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_agent_tools_search/search.py').read())" \
    || fail "syntax error in search.py"
PYTHONPATH="$pkg_dir" python3 -c "from aipc_agent_tools_search.search import self_test; self_test()" \
    >/dev/null || fail "self-test failed (JSON parsing / fail-soft / tavily not_configured)"

# search.tavily must be advertised only when TAVILY_API_KEY is actually configured.
PYTHONPATH="$pkg_dir" python3 -c "
import os
os.environ.pop('TAVILY_API_KEY', None)
from aipc_agent_tools_search.search import available_tools
assert available_tools() == ['search.searxng'], available_tools()
" >/dev/null || fail "search.tavily advertised without a configured key"

# SearXNG quadlet: hardware-verified only (needs a running container runtime).
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet aipc-searxng.service 2>/dev/null; then
    nc -z 127.0.0.1 8888 2>/dev/null || fail "aipc-searxng active but port 8888 unreachable"
    echo "agent-tools-search: static + self-test + quadlet OK (hardware-verified)"
else
    echo "agent-tools-search: static + self-test OK (render-verified; aipc-searxng.service not running here — expected without a container runtime/hardware)"
fi
