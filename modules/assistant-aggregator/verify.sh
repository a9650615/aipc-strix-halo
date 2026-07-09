#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "assistant-aggregator: disabled (optional)" >&2
    exit 2
fi

script="$this_dir/files/usr/bin/aipc-assistant"
lib="$this_dir/files/usr/lib/aipc_assistant"
[ -f "$script" ] || {
    echo "assistant-aggregator: missing aipc-assistant bin" >&2
    exit 1
}
[ -d "$lib" ] && [ -f "$lib/__init__.py" ] || {
    echo "assistant-aggregator: missing lib aipc_assistant" >&2
    exit 1
}

python3 -c "import ast; ast.parse(open('$script').read())" || {
    echo "assistant-aggregator: aipc-assistant syntax error" >&2
    exit 1
}

export AIPC_ASSISTANT_ETC="$this_dir/files/etc/aipc/assistant"
export PYTHONPATH="$this_dir/files/usr/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 "$script" --self-test || {
    echo "assistant-aggregator: self-test failed" >&2
    exit 1
}

for f in mode keywords.yaml features.yaml controller.yaml inject-policy.yaml runtime.yaml; do
    [ -f "$this_dir/files/etc/aipc/assistant/$f" ] || {
        echo "assistant-aggregator: missing etc $f" >&2
        exit 1
    }
done

echo "assistant-aggregator: ok"
exit 0
