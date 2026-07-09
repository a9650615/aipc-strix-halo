#!/bin/sh
set -eu
this_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

wake="$this_dir/files/usr/lib/aipc-voice/aipc_voice_wake.py"
[ -f "$wake" ] || {
  echo "voice-wake: missing aipc_voice_wake.py" >&2
  exit 1
}
python3 -c "import ast; ast.parse(open('$wake').read())" || {
  echo "voice-wake: syntax error" >&2
  exit 1
}
python3 "$wake" --self-test || {
  echo "voice-wake: self-test failed" >&2
  exit 1
}
unit="$this_dir/files/etc/systemd/system/aipc-voice-wake.service"
grep -q 'Conflicts=aipc-voice-mute.target' "$unit" || {
  echo "voice-wake: unit must Conflict mute target" >&2
  exit 1
}
train="$this_dir/files/usr/bin/aipc-voice-train-wake"
[ -f "$train" ] || {
  echo "voice-wake: missing train script" >&2
  exit 1
}
echo "voice-wake: static OK"
exit 0
