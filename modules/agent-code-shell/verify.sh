#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

wrapper="$this_dir/files/usr/lib/aipc-agent/aipc-code-shell"
if [ ! -x "$wrapper" ]; then
    echo "agent-code-shell: wrapper missing or not executable at $wrapper" >&2
    exit 1
fi

if ! python3 "$wrapper" --self-test >/dev/null 2>&1; then
    echo "agent-code-shell: wrapper self-test failed (fail-closed refusal logic broken)" >&2
    exit 1
fi

exit 0
