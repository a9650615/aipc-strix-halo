#!/bin/sh
set -eu
this_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

lib="$this_dir/files/usr/lib/aipc-voice"
wake="$lib/aipc_voice_wake.py"
policy_mod="$lib/aipc_voice_wake_policy.py"
session_mod="$lib/aipc_voice_session.py"
capture_mod="$lib/aipc_voice_capture.py"
once_mod="$lib/aipc_voice_once_worker.py"
for f in "$wake" "$policy_mod" "$session_mod" "$capture_mod" "$once_mod"; do
  [ -f "$f" ] || {
    echo "voice-wake: missing $(basename "$f")" >&2
    exit 1
  }
  python3 -c "import ast; ast.parse(open('$f').read())" || {
    echo "voice-wake: syntax error in $f" >&2
    exit 1
  }
done
PYTHONPATH="$lib${PYTHONPATH:+:$PYTHONPATH}" python3 "$wake" --self-test || {
  echo "voice-wake: self-test failed" >&2
  exit 1
}
# Anti-ghost / thrash helpers live in policy module
for sym in classify_wake_text decide_wake_arm miss_backoff_seconds junk_capture_action next_mode_after_empty_capture; do
  grep -q "def $sym" "$policy_mod" || {
    echo "voice-wake: missing helper $sym in policy" >&2
    exit 1
  }
done
grep -q 'class SessionState' "$session_mod" || {
  echo "voice-wake: missing SessionState" >&2
  exit 1
}
grep -q 'class PartialSttWorker' "$capture_mod" || {
  echo "voice-wake: missing PartialSttWorker in capture" >&2
  exit 1
}
grep -q 'class OnceWorker' "$once_mod" || {
  echo "voice-wake: missing OnceWorker" >&2
  exit 1
}
grep -q '_MANGLED_WAKE' "$policy_mod" "$wake" && {
  echo "voice-wake: _MANGLED_WAKE must not return" >&2
  exit 1
}
policy="$this_dir/files/etc/aipc/voice/wake-policy.env"
[ -f "$policy" ] || {
  echo "voice-wake: missing wake-policy.env" >&2
  exit 1
}
grep -q 'AIPC_WAKE_ALLOW_FUZZY_PROMOTE=0' "$policy" || {
  echo "voice-wake: policy must lock fuzzy promote off" >&2
  exit 1
}
unit="$this_dir/files/etc/systemd/system/aipc-voice-wake.service"
grep -q 'Conflicts=aipc-voice-mute.target' "$unit" || {
  echo "voice-wake: unit must Conflict mute target" >&2
  exit 1
}
grep -q 'wake-policy.env' "$unit" || {
  echo "voice-wake: unit must reference wake-policy.env" >&2
  exit 1
}
train="$this_dir/files/usr/bin/aipc-voice-train-wake"
[ -f "$train" ] || {
  echo "voice-wake: missing train script" >&2
  exit 1
}
echo "voice-wake: static OK"
exit 0
