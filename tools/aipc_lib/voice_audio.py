"""Media ducking + mic denoise + TTS playback (PipeWire/Pulse).

Critical UX rule — USER HARD BOUNDARY (violating this is a fireable bug):
  NEVER change the user's system / master volume level.
  Forbidden: `pactl set-sink-volume`, `wpctl set-volume`, `amixer … Master/Speaker N%`.
  Ducking only touches per-stream `set-sink-input-volume` (other apps), with fade.
  Unmute-only is allowed so TTS is not silent when the sink is muted.

Policy:
- Duck other sink-inputs while wake/recording/thinking (Mac-style fade, not jump).
- TTS plays at whatever master volume the user already set — never raise/lower it.
- Optional RNNoise capture path (aipc_denoise_out.monitor).
"""
from __future__ import annotations

import atexit
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DUCK_STATES = frozenset({"wake", "recording", "thinking"})
UNDUCK_STATES = frozenset(
    {"speaking", "listening", "done", "muted", "miss", "no_speech", "error", "detecting"}
)

DENOISE_SINK = "aipc_denoise_out"
DENOISE_LADSPA = "aipc_denoise_in"
DENOISE_SOURCE = f"{DENOISE_SINK}.monitor"

_duck_active = False
# sink-input index -> original volume percent
_saved_inputs: dict[int, int] = {}
_session_sink: str | None = None
_denoise_ready = False
_speaker_ensured = False
_duck_lock = threading.Lock()


def _is_forbidden_master_volume_cmd(argv: list[str]) -> bool:
    """True if argv would change master/system loudness (not just mute/port)."""
    if not argv:
        return False
    prog = os.path.basename(argv[0])
    # pactl set-sink-volume <sink> <vol>  — always forbidden
    if prog == "pactl" and len(argv) >= 2 and argv[1] == "set-sink-volume":
        return True
    # wpctl set-volume …
    if prog == "wpctl" and len(argv) >= 2 and argv[1] == "set-volume":
        return True
    # amixer … set Master|Speaker|PCM <N%>  (unmute-only is OK)
    if prog == "amixer" and "set" in argv:
        try:
            si = argv.index("set")
        except ValueError:
            return False
        rest = argv[si + 1 :]
        if not rest:
            return False
        control = rest[0]
        if control not in ("Master", "Speaker", "PCM", "Headphone"):
            return False
        for tok in rest[1:]:
            if tok in ("unmute", "mute", "toggle", "on", "off"):
                continue
            # any level like 100%, 50, 63 is a volume change
            if tok.endswith("%") or tok.isdigit() or re.match(r"^-?\d+(\.\d+)?dB$", tok):
                return True
    return False


def _run(argv: list[str], timeout: float = 3.0) -> subprocess.CompletedProcess:
    if _is_forbidden_master_volume_cmd(argv):
        msg = f"aipc-voice-audio: BLOCKED master volume cmd: {' '.join(argv)}"
        print(msg, file=sys.stderr, flush=True)
        return subprocess.CompletedProcess(argv, 1, "", msg)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_default_sink() -> str:
    return (_run(["pactl", "get-default-sink"]).stdout or "").strip()


def list_sinks() -> list[tuple[str, str]]:
    out = []
    for line in (_run(["pactl", "list", "short", "sinks"]).stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[1]
        state = parts[4] if len(parts) > 4 else ""
        if "aipc_denoise" in name:
            continue
        out.append((name, state))
    return out


def get_sink_volume_pct(sink: str = "@DEFAULT_SINK@") -> int | None:
    proc = _run(["pactl", "get-sink-volume", sink or "@DEFAULT_SINK@"])
    if proc.returncode != 0:
        return None
    m = re.search(r"/\s*(\d+)%", proc.stdout or "")
    return int(m.group(1)) if m else None


def get_default_sink_volume_pct() -> int | None:
    return get_sink_volume_pct("@DEFAULT_SINK@")


def duck_factor() -> float:
    try:
        return float(os.environ.get("AIPC_VOICE_DUCK_FACTOR", "0.30"))
    except ValueError:
        return 0.30


def duck_floor_pct() -> int:
    try:
        return int(os.environ.get("AIPC_VOICE_DUCK_FLOOR", "15"))
    except ValueError:
        return 15


def duck_enabled() -> bool:
    return os.environ.get("AIPC_VOICE_DUCK", "1") != "0"


def duck_fade_ms() -> int:
    """Mac-style fade duration for duck/unduck (0 = instant). Default 350ms."""
    try:
        return max(0, int(os.environ.get("AIPC_VOICE_DUCK_MS", "350")))
    except ValueError:
        return 350


def denoise_enabled() -> bool:
    return os.environ.get("AIPC_VOICE_DENOISE", "1") != "0"


def denoise_vad_threshold() -> str:
    return os.environ.get("AIPC_VOICE_DENOISE_VAD", "45")


def list_sink_inputs() -> list[dict]:
    """Parse `pactl list sink-inputs` into [{index, volume_pct, name}, ...]."""
    proc = _run(["pactl", "list", "sink-inputs"])
    text = proc.stdout or ""
    items: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("Sink Input #"):
            if cur:
                items.append(cur)
            try:
                idx = int(line.split("#", 1)[1].strip())
            except ValueError:
                cur = None
                continue
            cur = {"index": idx, "volume_pct": 100, "name": ""}
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("Volume:"):
            m = re.search(r"/\s*(\d+)%", s)
            if m:
                cur["volume_pct"] = int(m.group(1))
        elif "application.name" in s or "media.name" in s or "node.name" in s:
            # application.name = "Zen"
            if "=" in s:
                cur["name"] = s.split("=", 1)[1].strip().strip('"')
    if cur:
        items.append(cur)
    return items


def _is_tts_stream(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in ("paplay", "pw-play", "aipc-tts", "aipc", "tts", "ffplay", "mpv"))


def _set_input_volume(idx: int, pct: int) -> bool:
    pct = max(0, min(150, int(pct)))
    return _run(["pactl", "set-sink-input-volume", str(idx), f"{pct}%"]).returncode == 0


def _ease_in_out(t: float) -> float:
    """Smoothstep-ish cubic ease (Mac-like, not linear jump)."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def _fade_inputs(targets: dict[int, int], duration_ms: int) -> int:
    """Fade each sink-input from its current volume to targets[idx]. Never touches master."""
    if not targets:
        return 0
    current: dict[int, int] = {}
    for inp in list_sink_inputs():
        idx = int(inp["index"])
        if idx in targets:
            current[idx] = int(inp.get("volume_pct") or 100)
    for idx in targets:
        current.setdefault(idx, targets[idx])

    if duration_ms <= 0:
        ok = 0
        for idx, end in targets.items():
            if _set_input_volume(idx, end):
                ok += 1
        return ok

    step_ms = 35
    steps = max(2, int(round(duration_ms / step_ms)))
    ok_last = 0
    for s in range(1, steps + 1):
        e = _ease_in_out(s / steps)
        for idx, end in targets.items():
            start = current[idx]
            pct = int(round(start + (end - start) * e))
            if _set_input_volume(idx, pct):
                ok_last += 1 if s == steps else 0
        if s < steps:
            time.sleep(duration_ms / 1000.0 / steps)
    # final snap to exact targets (rounding)
    ok = 0
    for idx, end in targets.items():
        if _set_input_volume(idx, end):
            ok += 1
    return ok


def duck_start() -> None:
    """Lower OTHER apps' stream volumes with a short fade — never touch master sink."""
    global _duck_active, _saved_inputs, _session_sink
    if not duck_enabled():
        return
    with _duck_lock:
        _session_sink = get_default_sink() or _session_sink
        factor = duck_factor()
        floor = duck_floor_pct()
        saved: dict[int, int] = {}
        targets: dict[int, int] = {}
        for inp in list_sink_inputs():
            idx = int(inp["index"])
            name = str(inp.get("name") or "")
            if _is_tts_stream(name):
                continue
            # Keep previously saved original if we re-duck
            if idx in _saved_inputs:
                orig = _saved_inputs[idx]
            else:
                orig = int(inp.get("volume_pct") or 100)
                # If already partially ducked (re-entry), don't treat ducked level as original
                saved[idx] = orig
            saved.setdefault(idx, orig)
            target = max(floor, int(orig * factor))
            if target >= orig:
                continue
            targets[idx] = target
        _saved_inputs.update(saved)
        _duck_active = True
        if not targets:
            return
        n = _fade_inputs(targets, duck_fade_ms())
        if n:
            print(
                f"aipc-voice-audio: ducked {n} stream(s) over {duck_fade_ms()}ms (no master OSD)",
                flush=True,
            )


def duck_stop(*, instant: bool = False) -> None:
    """Restore per-stream volumes (fade unless instant=True for atexit/cleanup)."""
    global _duck_active, _saved_inputs
    with _duck_lock:
        if not _saved_inputs and not _duck_active:
            return
        targets = dict(_saved_inputs)
        _saved_inputs.clear()
        _duck_active = False
        if not targets:
            return
        ms = 0 if instant else duck_fade_ms()
        n = _fade_inputs(targets, ms)
        if n:
            print(
                f"aipc-voice-audio: restored {n} stream(s)"
                + (f" over {ms}ms" if ms else " (instant)"),
                flush=True,
            )


def is_ducked() -> bool:
    return _duck_active


def session_sink() -> str:
    global _session_sink
    if not _session_sink:
        _session_sink = get_default_sink()
    return _session_sink or ""


def _sink_is_muted(sink: str) -> bool:
    proc = _run(["pactl", "get-sink-mute", sink or "@DEFAULT_SINK@"])
    return "yes" in (proc.stdout or "").lower() or "是" in (proc.stdout or "")


def ensure_speaker_output(sink: str | None = None) -> str:
    """Unmute primary sink and prefer Speakers port (once per process).

    Avoid no-op mute/port changes: Plasma's audioshortcutsservice re-connects
    volumeChanged on every preferred-sink change, stacking volume OSD popups.
    """
    global _speaker_ensured, _session_sink
    sink = sink or get_default_sink()
    if not sink or "aipc_denoise" in sink:
        for name, _st in list_sinks():
            if "analog-stereo" in name:
                sink = name
                break
    if not sink:
        return ""
    _session_sink = sink
    # Unmute only when muted — never set-sink-volume (KDE volume OSD)
    if _sink_is_muted(sink):
        _run(["pactl", "set-sink-mute", sink, "0"])
    if not _speaker_ensured:
        # Only set port if not already on speakers (port flips re-stack OSD handlers)
        info = _run(["pactl", "list", "sinks"]).stdout or ""
        already_speaker = "analog-output-speaker" in info and "Active Port: analog-output-speaker" in info
        if not already_speaker:
            for port in ("analog-output-speaker", "analog-output-speaker-1"):
                if _run(["pactl", "set-sink-port", sink, port]).returncode == 0:
                    print(f"aipc-voice-audio: sink port {port} on {sink}", flush=True)
                    break
        for card in ("1", "0"):
            _run(["amixer", "-c", card, "set", "Master", "unmute"])
            _run(["amixer", "-c", card, "set", "Speaker", "unmute"])
        _speaker_ensured = True
    return sink


def playback_sinks() -> list[str]:
    """TTS → system primary output only."""
    override = (os.environ.get("AIPC_TTS_SINK") or "").strip()
    if override:
        return [override]
    default = get_default_sink()
    if default and "aipc_denoise" not in default:
        return [default]
    for name, _state in list_sinks():
        if "aipc_denoise" not in name:
            return [name]
    return [default] if default else []


@contextmanager
def full_volume_for_playback():
    """Prepare for TTS: unduck other streams, unmute speakers. No master vol change."""
    # Restore other apps so mix is sane, then TTS plays at system volume
    duck_stop()
    sink = ensure_speaker_output(session_sink() or get_default_sink())
    sinks = playback_sinks()
    if sink and sink not in sinks:
        sinks = [sink]
    print(f"aipc-voice-audio: TTS sinks={sinks} (master volume untouched)", flush=True)
    try:
        yield sinks
    finally:
        # Stay unducked after TTS (session usually ends with speaking→done)
        pass


def ensure_denoise_source() -> str | None:
    global _denoise_ready
    if not denoise_enabled():
        return None
    if not Path("/usr/lib64/ladspa/librnnoise_ladspa.so").is_file() and not Path(
        "/usr/lib/ladspa/librnnoise_ladspa.so"
    ).is_file():
        return None
    if _denoise_ready or DENOISE_SINK in (_run(["pactl", "list", "short", "modules"]).stdout or ""):
        _denoise_ready = True
        return DENOISE_SOURCE

    proc = _run(["pactl", "get-default-source"])
    mic = (proc.stdout or "").strip()
    if not mic or "aipc_denoise" in mic:
        ls = _run(["pactl", "list", "short", "sources"])
        for line in (ls.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and "input" in parts[1] and "monitor" not in parts[1]:
                mic = parts[1]
                break
    if not mic:
        return None

    # device.class=filter keeps these off Plasma's preferred output list
    # (null-sink appearance was stacking volume OSD handlers in kded).
    _run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={DENOISE_SINK}",
            "sink_properties=device.description=AIPC_Denoise device.class=filter device.icon_name=audio-input-microphone",
        ]
    )
    _run(
        [
            "pactl",
            "load-module",
            "module-ladspa-sink",
            f"sink_name={DENOISE_LADSPA}",
            f"sink_master={DENOISE_SINK}",
            "plugin=librnnoise_ladspa",
            "label=noise_suppressor_mono",
            f"control={denoise_vad_threshold()}",
            "sink_properties=device.description=AIPC_Denoise_In device.class=filter",
        ]
    )
    _run(
        [
            "pactl",
            "load-module",
            "module-loopback",
            f"source={mic}",
            f"sink={DENOISE_LADSPA}",
            "channels=1",
            "latency_msec=25",
            "source_dont_move=true",
            "sink_dont_move=true",
        ]
    )
    _denoise_ready = True
    print(f"aipc-voice-audio: denoise {DENOISE_SOURCE}", flush=True)
    return DENOISE_SOURCE


def capture_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    src = ensure_denoise_source()
    if src:
        env["PULSE_SOURCE"] = src
    return env


def on_voice_state(state: str) -> None:
    global _session_sink
    if state in DUCK_STATES:
        if not _session_sink:
            _session_sink = get_default_sink()
        duck_start()
    elif state == "speaking":
        duck_stop()
    elif state in ("listening", "done", "muted"):
        duck_stop()
        _session_sink = None
    elif state in UNDUCK_STATES:
        duck_stop()


atexit.register(lambda: duck_stop(instant=True))
