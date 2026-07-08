#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

voice_once="$this_dir/files/usr/bin/aipc-voice-once"
hotkey="$this_dir/files/usr/bin/aipc-voice-bind-hotkey"
python3 -c "import ast; ast.parse(open('$voice_once').read())" || {
    echo "voice-pipecat: aipc-voice-once syntax error" >&2
    exit 1
}
python3 "$voice_once" --self-test >/dev/null || {
    echo "voice-pipecat: aipc-voice-once self-test failed" >&2
    exit 1
}
python3 -c "import ast; ast.parse(open('$hotkey').read())" || {
    echo "voice-pipecat: aipc-voice-bind-hotkey syntax error" >&2
    exit 1
}
python3 "$hotkey" --self-test >/dev/null || {
    echo "voice-pipecat: aipc-voice-bind-hotkey self-test failed" >&2
    exit 1
}

exit 0
