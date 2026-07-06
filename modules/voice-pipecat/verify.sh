#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

src="$this_dir/files/usr/bin/aipc-voice-once"
python3 -c "import ast; ast.parse(open('$src').read())" || {
    echo "voice-pipecat: aipc-voice-once syntax error" >&2
    exit 1
}
python3 "$src" --self-test >/dev/null || {
    echo "voice-pipecat: aipc-voice-once self-test failed" >&2
    exit 1
}

exit 0
