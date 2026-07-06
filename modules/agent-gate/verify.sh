#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi
pkg_dir="$this_dir/files/usr/lib/aipc-agent"

fail() { echo "agent-gate: $*" >&2; exit 1; }

for f in __init__.py store.py audit.py server.py; do
    [ -f "$pkg_dir/aipc_agent_gate/$f" ] || fail "$f missing"
    python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_agent_gate/$f').read())" \
        || fail "syntax error in $f"
done

PYTHONPATH="$pkg_dir" python3 -m aipc_agent_gate.server --self-test >/dev/null \
    || fail "self-test failed (grant/check/revoke/expiry/reload logic)"

# Runtime tier: if the service is actually up (post-rebuild, or live-
# hotfixed per docs/live-hotfix-workflow.md), exercise the real socket.
if systemctl is-active --quiet aipc-agent-gate.service 2>/dev/null; then
    [ -S /run/aipc-agent-gate.sock ] || fail "service active but socket missing"
    resp=$(python3 -c "
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(2.0)
s.connect('/run/aipc-agent-gate.sock')
s.sendall(b'{\"cmd\": \"status\"}\n')
print(s.recv(65536).decode().strip())
") || fail "socket RPC round-trip failed"
    echo "agent-gate: static + self-test + live socket OK (hardware-verified; status=$resp)"
else
    echo "agent-gate: static + self-test OK (render-verified; service not active on this run)"
fi
exit 0
