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

DUCK_STATES = frozenset({"wake", "recording", "thinking", "working"})
UNDUCK_STATES = frozenset(
    {"speaking", "listening", "done", "muted", "miss", "no_speech", "error", "detecting", "followup"}
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
    """How loud other apps stay while ducking (1.0 = no change).

    Soft default: keep media listenable (~55%) while still leaving headroom
    for the mic; recognition uses adaptive bleed thr, not hard silence.
    """
    try:
        return float(os.environ.get("AIPC_VOICE_DUCK_FACTOR", "0.55"))
    except ValueError:
        return 0.55


def duck_floor_pct() -> int:
    """Never duck other streams below this % (listenable floor)."""
    try:
        return int(os.environ.get("AIPC_VOICE_DUCK_FLOOR", "40"))
    except ValueError:
        return 40


def duck_enabled() -> bool:
    return os.environ.get("AIPC_VOICE_DUCK", "1") != "0"


def duck_fade_ms() -> int:
    """Mac-style fade duration for duck/unduck (0 = instant). Default 200ms."""
    try:
        return max(0, int(os.environ.get("AIPC_VOICE_DUCK_MS", "200")))
    except ValueError:
        return 200


def denoise_enabled() -> bool:
    return os.environ.get("AIPC_VOICE_DENOISE", "1") != "0"


def denoise_vad_threshold() -> str:
    # Higher = more aggressive ambient suppression (RNNoise VAD %).
    return os.environ.get("AIPC_VOICE_DENOISE_VAD", "80")


def list_sink_inputs() -> list[dict]:
    """Parse `pactl list sink-inputs` into [{index, volume_pct, name, state}, ...]."""
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
            cur = {
                "index": idx,
                "volume_pct": 100,
                "name": "",
                "sink": "",
                "target": "",
                "state": "",
                "corked": False,
                "props": "",
            }
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("Volume:"):
            m = re.search(r"/\s*(\d+)%", s)
            if m:
                cur["volume_pct"] = int(m.group(1))
        elif s.startswith("State:"):
            cur["state"] = s.split(":", 1)[1].strip().upper()
        elif s.startswith("Corked:"):
            cur["corked"] = "yes" in s.lower()
        elif s.startswith("Sink:"):
            # numeric id or name depending on pactl version
            cur["sink"] = s.split(":", 1)[1].strip()
        elif "=" in s and any(
            k in s
            for k in (
                "application.name",
                "media.name",
                "node.name",
                "target.object",
                "device.description",
                "node.group",
                "node.link-group",
            )
        ):
            key = s.split("=", 1)[0].strip().lower()
            val = s.split("=", 1)[1].strip().strip('"')
            cur["props"] = f"{cur.get('props') or ''} {key}={val}"
            if "target.object" in key:
                cur["target"] = val
            if "application.name" in key:
                cur["name"] = val
            elif not cur["name"] and (
                "media.name" in key or "node.name" in key or "device.description" in key
            ):
                cur["name"] = val
    if cur:
        items.append(cur)
    return items


def _is_tts_stream(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in ("paplay", "pw-play", "aipc-tts", "aipc-voice", "tts", "ffplay"))


def _is_aipc_internal_stream(inp: dict) -> bool:
    """Denoise null-sink / RNNoise loopback must not count as media playback."""
    blob = " ".join(
        str(inp.get(k) or "")
        for k in ("name", "sink", "target", "props")
    ).lower()
    return any(
        k in blob
        for k in (
            "aipc_denoise",
            "aipc-denoise",
            "denoise_in",
            "denoise_out",
            "noise_suppressor",
            "filter-chain-",  # PipeWire ladspa filter chain for denoise
            "ladspa-sink-",
            "aipc_denoise_in",
            "aipc_denoise_out",
        )
    )


def playback_active(*, include_tts: bool = False) -> bool:
    """True if speakers are likely producing sound (any non-corked sink-input).

    Used to raise mic energy gates so speaker bleed is not treated as speech.
    Ignores aipc denoise filter graph (always present; was false-positive playback).
    """
    for inp in list_sink_inputs():
        name = str(inp.get("name") or "")
        if _is_aipc_internal_stream(inp):
            continue
        if not include_tts and _is_tts_stream(name):
            continue
        if inp.get("corked"):
            continue
        state = str(inp.get("state") or "")
        # RUNNING or empty (some PipeWire builds omit State)
        if state in ("", "RUNNING", "IDLE"):
            # IDLE still often means a held stream; count if volume > 0
            if int(inp.get("volume_pct") or 0) <= 0:
                continue
            return True
    return False


def tts_playback_active() -> bool:
    """True if our TTS / paplay stream is currently on a sink."""
    for inp in list_sink_inputs():
        if _is_tts_stream(str(inp.get("name") or "")) and not inp.get("corked"):
            return True
    return False


def effective_energy_thr(
    base: float,
    *,
    playback: bool,
    ratio: float | None = None,
    extra: float | None = None,
    floor: float = 12000.0,
    bleed_floor: float = 0.0,
) -> float:
    """Raise mic energy gate while speakers play so bleed is not treated as speech.

    Prefer adaptive `bleed_floor` (EMA of mic while music plays) so we do not
    need to mute media for recognition — thr sits just above speaker bleed.
    Pure function — unit-tested without pactl.
    """
    if not playback:
        return float(base)
    if ratio is None:
        try:
            ratio = float(os.environ.get("AIPC_WAKE_PLAYBACK_ENERGY_RATIO", "1.55"))
        except ValueError:
            ratio = 1.55
    if extra is None:
        try:
            extra = float(os.environ.get("AIPC_WAKE_PLAYBACK_ENERGY_EXTRA", "3500"))
        except ValueError:
            extra = 3500.0
    # Adaptive: thr ≈ bleed * 1.45 + margin (user voice over music)
    adaptive = 0.0
    if bleed_floor > 0:
        try:
            br = float(os.environ.get("AIPC_WAKE_BLEED_RATIO", "1.45"))
        except ValueError:
            br = 1.45
        try:
            bm = float(os.environ.get("AIPC_WAKE_BLEED_MARGIN", "2800"))
        except ValueError:
            bm = 2800.0
        adaptive = float(bleed_floor) * br + bm
    fixed = max(float(base) * float(ratio), float(base) + float(extra), float(floor))
    if adaptive > 0:
        # Cap so continuous loud media does not push thr out of human range
        try:
            # Cap must stay in human voice range (~12–22k RMS on this hardware).
            # 28k made wake/PTT deaf while media played (user speech ~16k lost).
            cap = float(os.environ.get("AIPC_WAKE_PLAYBACK_THR_CAP", "16000"))
        except ValueError:
            cap = 16000.0
        return min(max(fixed * 0.55, adaptive, float(base) * 1.2), cap)
    return fixed


def update_bleed_floor(ema: float, rms: float, *, alpha_down: float = 0.12, alpha_up: float = 0.04) -> float:
    """Track non-speech mic level (speaker bleed + room). Slow up, faster down."""
    r = float(rms)
    if ema <= 0:
        return r
    if r <= ema:
        return (1.0 - alpha_down) * ema + alpha_down * r
    return (1.0 - alpha_up) * ema + alpha_up * r


def barge_energy_thr(
    base: float,
    *,
    bleed_peak: float = 0.0,
    ratio: float | None = None,
    min_rms: float | None = None,
    over_bleed: float | None = None,
) -> float:
    """Threshold for barge-in: must beat ambient thr and recent TTS→mic bleed."""
    if ratio is None:
        try:
            ratio = float(os.environ.get("AIPC_WAKE_BARGE_ENERGY_RATIO", "1.85"))
        except ValueError:
            ratio = 1.85
    if min_rms is None:
        try:
            min_rms = float(os.environ.get("AIPC_WAKE_BARGE_MIN_RMS", "20000"))
        except ValueError:
            min_rms = 20000.0
    if over_bleed is None:
        try:
            over_bleed = float(os.environ.get("AIPC_WAKE_BARGE_OVER_BLEED", "1.35"))
        except ValueError:
            over_bleed = 1.35
    return max(
        float(base) * float(ratio),
        float(min_rms),
        float(base) + 6000.0,
        float(bleed_peak) * float(over_bleed),
    )


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
        already = _duck_active
        _saved_inputs.update(saved)
        _duck_active = True
        if not targets:
            return
        # Re-entry (wake→recording→thinking): don't re-spend a full fade each state.
        ms = 0 if already else duck_fade_ms()
        n = _fade_inputs(targets, ms)
        if n:
            print(
                f"aipc-voice-audio: ducked {n} stream(s)"
                + (f" over {ms}ms" if ms else " (already ducked)")
                + " (no master OSD)",
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
    """TTS output sinks — prefer hearing the assistant.

    Default sink alone is wrong when BT headphones are default but not worn:
    TTS goes only to AirPods and laptop speakers stay silent. Always include a
    hardware analog/HDMI speaker sink when present, plus the default (if different).
    Override with AIPC_TTS_SINK=exact_name for a single sink.
    """
    override = (os.environ.get("AIPC_TTS_SINK") or "").strip()
    if override:
        return [override]
    multi = (os.environ.get("AIPC_TTS_MULTI_SINK", "1").strip() != "0")
    sinks = list_sinks()
    names = [n for n, _st in sinks if n and "aipc_denoise" not in n]
    default = get_default_sink()
    out: list[str] = []

    def _add(name: str | None) -> None:
        if name and name not in out and "aipc_denoise" not in name:
            out.append(name)

    # Prefer built-in analog speaker first when multi-sink (user often hears this).
    for n in names:
        if "analog-stereo" in n or "analog_output" in n.lower():
            _add(n)
            break
    if multi:
        for n in names:
            if "hdmi" in n.lower() or "pci-" in n:
                _add(n)
        _add(default)
        # Cap: speaker + default is enough; avoid blasting every BT device.
        return out[:3] if out else ([default] if default else [])
    _add(default)
    if out:
        return out
    return names[:1] if names else []


@contextmanager
def full_volume_for_playback():
    """Prepare for TTS: unduck other streams, unmute speakers. No master vol change."""
    # Restore other apps so mix is sane, then TTS plays at system volume
    duck_stop()
    speaker = ensure_speaker_output(session_sink() or get_default_sink())
    sinks = playback_sinks()
    # Ensure the unmuted hardware speaker is in the play list (multi-sink safe).
    if speaker and speaker not in sinks:
        sinks = [speaker] + list(sinks)
    print(f"aipc-voice-audio: TTS sinks={sinks} (master volume untouched)", flush=True)
    try:
        yield sinks
    finally:
        # Stay unducked after TTS (session usually ends with speaking→done)
        pass


def _denoise_modules_present() -> bool:
    text = _run(["pactl", "list", "short", "modules"]).stdout or ""
    return DENOISE_SINK in text or "aipc_denoise" in text or "librnnoise" in text


def _denoise_control_matches() -> bool:
    """True if loaded RNNoise control equals current env threshold."""
    want = denoise_vad_threshold()
    text = _run(["pactl", "list", "modules"]).stdout or ""
    # Look for our ladspa line: control=NN
    for block in text.split("Module #"):
        if "librnnoise" not in block and "aipc_denoise_in" not in block:
            continue
        m = re.search(r"control=([0-9.]+)", block)
        if m and m.group(1).split(".")[0] == str(want).split(".")[0]:
            return True
        if "librnnoise" in block or "aipc_denoise_in" in block:
            return False
    return False


def unload_denoise_chain() -> None:
    """Tear down aipc denoise null/ladspa/loopback modules (idempotent)."""
    global _denoise_ready
    text = _run(["pactl", "list", "modules"]).stdout or ""
    # Unload in reverse dependency order: loopback → ladspa → null
    ids: list[str] = []
    cur = None
    for line in text.splitlines():
        if line.startswith("Module #"):
            cur = line.split("#", 1)[1].strip()
            continue
        if cur and (
            "aipc_denoise" in line
            or "librnnoise" in line
            or ("loopback" in line and "aipc_denoise" in line)
        ):
            ids.append(cur)
            cur = None
    # Also match Argument lines with aipc_denoise in full module dump
    cur = None
    for line in text.splitlines():
        if line.startswith("Module #"):
            cur = line.split("#", 1)[1].strip()
        if cur and "aipc_denoise" in line:
            if cur not in ids:
                ids.append(cur)
    for mid in reversed(ids):
        _run(["pactl", "unload-module", mid])
    # Fallback: short list by name fragments
    for line in (_run(["pactl", "list", "short", "modules"]).stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        mid, name = parts[0], parts[1]
        args = "\t".join(parts[2:]) if len(parts) > 2 else ""
        if "aipc_denoise" in args or "librnnoise" in args:
            _run(["pactl", "unload-module", mid])
        elif name == "module-loopback" and "aipc_denoise" in args:
            _run(["pactl", "unload-module", mid])
    _denoise_ready = False


def ensure_mic_capture_level() -> None:
    """Soft-cap analog input gain so 100% hardware capture does not clip RMS.

    At 100% this machine's built-in mic hits absmax=32768 on ambient alone and
    blinds wake VAD (energy thr races to 12–28k). Default soft gain 65%.
    """
    try:
        pct = int(os.environ.get("AIPC_WAKE_MIC_VOLUME_PCT", "65"))
    except ValueError:
        pct = 65
    if pct <= 0:
        return
    pct = max(20, min(100, pct))
    proc = _run(["pactl", "get-default-source"])
    mic = (proc.stdout or "").strip()
    if not mic or "aipc_denoise" in mic or "monitor" in mic:
        ls = _run(["pactl", "list", "short", "sources"])
        for line in (ls.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and "input" in parts[1] and "monitor" not in parts[1]:
                if "aipc_denoise" not in parts[1]:
                    mic = parts[1]
                    break
    if not mic:
        return
    _run(["pactl", "set-source-volume", mic, f"{pct}%"])


def ensure_denoise_source() -> str | None:
    global _denoise_ready
    # Always soft-cap mic gain even if RNNoise plugin missing
    try:
        ensure_mic_capture_level()
    except Exception:
        pass
    if not denoise_enabled():
        return None
    if not Path("/usr/lib64/ladspa/librnnoise_ladspa.so").is_file() and not Path(
        "/usr/lib/ladspa/librnnoise_ladspa.so"
    ).is_file():
        return None

    reload = os.environ.get("AIPC_VOICE_DENOISE_RELOAD", "0") == "1"
    if _denoise_modules_present():
        if not reload and _denoise_control_matches():
            _denoise_ready = True
            return DENOISE_SOURCE
        unload_denoise_chain()

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
    thr = denoise_vad_threshold()
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
            f"control={thr}",
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
    print(f"aipc-voice-audio: denoise {DENOISE_SOURCE} vad={thr}", flush=True)
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
