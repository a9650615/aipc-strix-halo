#!/bin/sh
# verify.sh — system-aipc-portal
# Exit 0 = pass, 2 = optional/disabled, other = fail.
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
fail() { echo "aipc-portal: $*" >&2; exit 1; }

pkg_dir="$this_dir/files/usr/lib/aipc-portal"
[ -f "$pkg_dir/aipc_portal/server.py" ] || fail "server.py missing"
[ -f "$pkg_dir/aipc_portal/registry.py" ] || fail "registry.py missing"
[ -f "$this_dir/files/etc/aipc/portal/services/aipc-portal.yaml" ] || fail "self metadata missing"
[ -f "$this_dir/files/etc/systemd/system/aipc-portal.service" ] || fail "unit missing"
[ -f "$this_dir/env/endpoint" ] || fail "env/endpoint missing"

python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_portal/server.py').read())" \
  || fail "syntax error in server.py"
python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_portal/registry.py').read())" \
  || fail "syntax error in registry.py"

grep -q '127.0.0.1' "$this_dir/files/etc/systemd/system/aipc-portal.service" \
  || grep -q '127.0.0.1' "$pkg_dir/aipc_portal/__init__.py" \
  || fail "must bind 127.0.0.1"

if ! command -v systemctl >/dev/null 2>&1 \
  || ! systemctl is-active --quiet aipc-portal.service 2>/dev/null; then
  echo "aipc-portal: static OK (service not active; no live hardware check)" >&2
  exit 0
fi

curl -sf http://127.0.0.1:7080/healthz >/dev/null || fail "GET /healthz failed"
curl -sf http://127.0.0.1:7080/ >/dev/null || fail "GET / failed"
echo "aipc-portal: static + hardware OK"
