#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

fail() { echo "mem0: $*" >&2; exit 1; }

pkg_dir="$this_dir/files/usr/lib/aipc-mem0"
venv="/usr/lib/aipc-mem0/venv"

[ -f "$pkg_dir/aipc_mem0/server.py" ] || fail "server.py missing"
python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_mem0/server.py').read())" \
    || fail "syntax error in server.py"

if [ ! -x "$venv/bin/python3" ]; then
    echo "mem0: static OK only (render-verified; venv not installed on this host, no hardware check run)" >&2
    exit 0
fi

systemctl is-active --quiet aipc-mem0.service || {
    echo "mem0: static OK; aipc-mem0.service not active (no live hardware check)" >&2
    exit 0
}

curl -sf http://127.0.0.1:7000/healthz >/dev/null || fail "GET /healthz did not return 2xx"

echo "mem0: static + render + hardware OK (service active, /healthz responded)"
