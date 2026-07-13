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

timing_lib="$this_dir/files/usr/lib/aipc-voice/aipc_voice_timing.py"
python3 -c "import ast; ast.parse(open('$timing_lib').read())" || {
    echo "voice-pipecat: aipc_voice_timing syntax error" >&2
    exit 1
}
python3 "$timing_lib" >/dev/null || {
    echo "voice-pipecat: aipc_voice_timing self-test failed" >&2
    exit 1
}

bluetooth_recovery="$this_dir/files/etc/aipc/aipc_bluetooth_audio_recover.py"
python3 -c "import ast; ast.parse(open('$bluetooth_recovery').read())" || {
    echo "voice-pipecat: Bluetooth recovery syntax error" >&2
    exit 1
}
PYTHONPATH="$this_dir/files/etc/aipc" \
    python3 "$this_dir/tests/test_bluetooth_audio_recover.py" >/dev/null || {
    echo "voice-pipecat: Bluetooth recovery tests failed" >&2
    exit 1
}
python3 "$this_dir/files/etc/aipc/aipc-bluetooth-audio-recover" --self-test >/dev/null || {
    echo "voice-pipecat: Bluetooth recovery self-test failed" >&2
    exit 1
}

[ -f "$this_dir/files/usr/lib/systemd/user/aipc-bluetooth-audio-recover.service" ] || {
    echo "voice-pipecat: missing Bluetooth recovery unit" >&2
    exit 1
}
[ -f "$this_dir/files/etc/wireplumber/wireplumber.conf.d/51-aipc-audio-routing.conf" ] || {
    echo "voice-pipecat: missing audio routing config" >&2
    exit 1
}

exit 0
