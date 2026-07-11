#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

check_script() {
    script_name="$1"
    script_path="$this_dir/files/usr/bin/$script_name"
    python3 -c "import ast; ast.parse(open('$script_path').read())" || {
        echo "voice-pipecat: $script_name syntax error" >&2
        exit 1
    }
    python3 "$script_path" --self-test >/dev/null || {
        echo "voice-pipecat: $script_name self-test failed" >&2
        exit 1
    }
}

for script in aipc-voice-once aipc-voice-bind-hotkey aipc-voice-stream; do
    check_script "$script"
done

for script in aipc-voice-status aipc-voice-record-clone; do
    script_path="$this_dir/files/usr/bin/$script"
    [ -f "$script_path" ] || {
        echo "voice-pipecat: missing $script" >&2
        exit 1
    }
    python3 -c "import ast; ast.parse(open('$script_path').read())" || {
        echo "voice-pipecat: $script syntax error" >&2
        exit 1
    }
done

hotkey_file="$this_dir/files/etc/aipc/voice/hotkey"
[ -f "$hotkey_file" ] || {
    echo "voice-pipecat: missing hotkey config" >&2
    exit 1
}

autostart_file="$this_dir/files/etc/xdg/autostart/aipc-voice-hotkey.desktop"
[ -f "$autostart_file" ] || {
    echo "voice-pipecat: missing KDE autostart desktop file" >&2
    exit 1
}

tts="$this_dir/files/usr/lib/aipc-voice/aipc_voice_tts.py"
python3 -c "import ast; ast.parse(open('$tts').read())" || {
    echo "voice-pipecat: aipc_voice_tts syntax error" >&2
    exit 1
}
python3 "$tts" >/dev/null || {
    echo "voice-pipecat: aipc_voice_tts self-test failed" >&2
    exit 1
}

stream_lib="$this_dir/files/usr/lib/aipc-voice/aipc_voice_stream.py"
python3 -c "import ast; ast.parse(open('$stream_lib').read())" || {
    echo "voice-pipecat: aipc_voice_stream syntax error" >&2
    exit 1
}
python3 "$stream_lib" >/dev/null || {
    echo "voice-pipecat: aipc_voice_stream self-test failed" >&2
    exit 1
}

exit 0
