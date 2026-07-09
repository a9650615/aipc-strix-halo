#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "assistant-chatgpt: disabled (optional)" >&2
    exit 2
fi

script="$this_dir/files/usr/bin/aipc-chatgpt"
lib="$this_dir/files/usr/lib/aipc_chatgpt"
[ -f "$script" ] || {
    echo "assistant-chatgpt: missing aipc-chatgpt" >&2
    exit 1
}
[ -f "$lib/__init__.py" ] || {
    echo "assistant-chatgpt: missing package" >&2
    exit 1
}
python3 -c "import ast; ast.parse(open('$script').read())" || {
    echo "assistant-chatgpt: syntax error" >&2
    exit 1
}
export PYTHONPATH="$this_dir/files/usr/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 "$script" --self-test || {
    echo "assistant-chatgpt: self-test failed" >&2
    exit 1
}
if ! python3 -c "import playwright" 2>/dev/null; then
    echo "assistant-chatgpt: playwright python package missing (optional runtime)" >&2
    exit 2
fi
echo "assistant-chatgpt: ok"
exit 0
