#!/bin/bash
# Static + logic checks (§9). Render-verified, NOT hardware-verified — see
# the .disabled marker. Exit 0 = pass, non-zero = fail with one-line stderr.
set -e
src=modules/system-memory-oom-guard/files/usr/lib/aipc-oom-guard/oom_guard.py

fail() { echo "oom-guard: $*" >&2; exit 1; }

[ -f "$src" ] || fail "daemon missing"
python3 -c "import ast; ast.parse(open('$src').read())" || fail "syntax error"
python3 "$src" --self-test >/dev/null || fail "self-test failed (classify/priority/protected)"

echo "oom-guard: static + self-test OK (render-verified; not hardware-verified)"
