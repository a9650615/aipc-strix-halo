#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

PKG_DIR="$this_dir/files/usr/lib/aipc-codexbar-usage"
AIPC_VENV="/usr/lib/aipc/tools/.venv"
ok=0

if [ -d "$AIPC_VENV" ] && [ -x "$AIPC_VENV/bin/python" ]; then
    if "$AIPC_VENV/bin/python" -c "import codexbar_usage, codexbar_usage.cli, codexbar_usage.fetch, codexbar_usage.cost" 2>/dev/null; then
        ok=1
    fi
fi

if [ "$ok" -eq 0 ] && [ -d "$PKG_DIR/codexbar_usage" ]; then
    if PYTHONPATH="$PKG_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -c "import codexbar_usage, codexbar_usage.cli, codexbar_usage.fetch, codexbar_usage.cost, codexbar_usage.providers" 2>/dev/null; then
        ok=1
    fi
fi

if [ "$ok" -eq 0 ]; then
    echo "dev-ai-codexbar-usage: package not importable" >&2
    exit 1
fi

# Ensure provider package is not shadowed by a sibling providers.py
if [ -f "$PKG_DIR/codexbar_usage/providers.py" ]; then
    echo "dev-ai-codexbar-usage: providers.py shadows providers/ package" >&2
    exit 1
fi

echo "dev-ai-codexbar-usage: verification passed"
exit 0
