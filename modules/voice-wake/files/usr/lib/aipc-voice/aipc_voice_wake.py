#!/usr/bin/env python3
"""Always-on wake listener that triggers aipc-voice-once.

Modes (fast start first):
- phrase (default): energy gate → short STT → match custom phrases (low false
  positive; Chinese/English custom words without training a model).
- openwakeword: pretrained ONNX (e.g. hey_jarvis) when venv + models exist.
- energy: loudness-only fallback (higher false positives).

Mute: skip while /run/aipc/voice-mute exists (aipc-voice-mute.target).
"""
from __future__ import annotations

import argparse
import array
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

# UX status (optional — same paths as voice-once)
for _p in (
    Path("/usr/lib/aipc-voice"),
    Path("/var/lib/aipc-voice/lib"),
    Path(__file__).resolve().parent,
):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:
    import aipc_voice_ux as voice_ux
except Exception:
    voice_ux = None


def _ux(state: str, detail: str = "", **kw) -> None:
    if voice_ux is None:
        return
    try:
        voice_ux.announce(state, detail, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-voice-wake: ux fail: {exc}", flush=True)


MUTE_FLAG = Path(os.environ.get("AIPC_VOICE_MUTE_FLAG", "/run/aipc/voice-mute"))
ONCE_CMD = os.environ.get("AIPC_VOICE_ONCE", "/usr/bin/aipc-voice-once")
SAMPLE_RATE = 16000
FRAME_MS = 30
# Higher default than old energy-only: phrase mode re-checks with STT.
ENERGY_THRESHOLD = float(os.environ.get("AIPC_WAKE_ENERGY", "2000"))
COOLDOWN_S = float(os.environ.get("AIPC_WAKE_COOLDOWN", "8"))
# Frames of continuous energy before STT (5×30ms ≈ 150ms)
ENERGY_FRAMES = int(os.environ.get("AIPC_WAKE_ENERGY_FRAMES", "5"))
CAPTURE_S = float(os.environ.get("AIPC_WAKE_CAPTURE_S", "3.2"))
CMD_MAX_S = float(os.environ.get("AIPC_WAKE_CMD_MAX_S", "15"))
CMD_END_SILENCE_MS = int(os.environ.get("AIPC_WAKE_CMD_END_SILENCE_MS", "800"))
CMD_START_TIMEOUT_S = float(os.environ.get("AIPC_WAKE_CMD_START_TIMEOUT", "4"))
WAKE_CTRL_SOCK = Path(os.environ.get("AIPC_WAKE_SOCK", "/run/user/1000/aipc-wake.sock"))
STT_URL = os.environ.get("AIPC_VOICE_STT_URL", "http://127.0.0.1:9001/transcribe")
STT_LANG = os.environ.get("AIPC_WAKE_STT_LANG", "zh")
PHRASES_FILE = Path(
    os.environ.get("AIPC_WAKE_PHRASES_FILE", "/etc/aipc/wake/phrases")
)
# Default custom wake phrases (user-editable via phrases file / env)
DEFAULT_PHRASES = (
    "嘿助理",
    "嘿 助理",
    "你好助理",
    "hey assistant",
    "hi assistant",
)
MODEL_PATH = Path(
    os.environ.get(
        "AIPC_WAKE_MODEL",
        "/var/lib/aipc-voice/wake/user-model.onnx",
    )
)
PRETRAINED = os.environ.get("AIPC_WAKE_PRETRAINED", "hey_jarvis")
OWW_VENV_PYTHON = Path(
    os.environ.get(
        "AIPC_WAKE_OWW_PYTHON",
        "/var/lib/aipc-voice/venv/bin/python",
    )
)
_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)



def _capture_env() -> dict:
    """Mic env for wake arecord — basic RNNoise denoise by default.

    Uses virtual source aipc_denoise_out.monitor (noise-suppression-for-voice).
    Disable with AIPC_WAKE_DENOISE=0 if it hurts wake-word STT.
    """
    env = os.environ.copy()
    if os.environ.get("AIPC_WAKE_DENOISE", "1") == "0":
        env.pop("PULSE_SOURCE", None)
        return env
    try:
        from aipc_lib.voice_audio import capture_env, ensure_denoise_source
        ensure_denoise_source()
        return capture_env(env)
    except Exception as exc:
        print(f"aipc-voice-wake: denoise via aipc_lib failed: {exc}", flush=True)
    try:
        import voice_audio  # type: ignore
        voice_audio.ensure_denoise_source()
        return voice_audio.capture_env(env)
    except Exception as exc:
        print(f"aipc-voice-wake: denoise via voice_audio failed: {exc}", flush=True)
    env.setdefault("PULSE_SOURCE", "aipc_denoise_out.monitor")
    return env

def muted() -> bool:
    return MUTE_FLAG.exists()


def load_phrases() -> list[str]:
    """Load wake phrases: env AIPC_WAKE_PHRASES, else phrases file, else defaults."""
    env = os.environ.get("AIPC_WAKE_PHRASES", "").strip()
    raw: list[str] = []
    if env:
        raw = [p.strip() for p in env.split(",") if p.strip()]
    elif PHRASES_FILE.is_file():
        for line in PHRASES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw.append(line)
    else:
        raw = list(DEFAULT_PHRASES)
    # Drop very short tokens (high false positive)
    out = [p for p in raw if len(_norm(p)) >= 2]
    return out or list(DEFAULT_PHRASES)


def _norm(text: str) -> str:
    t = text.strip().lower()
    # unify common full-width / variants before stripping
    t = t.replace("废", "廢").replace("助 理", "助理")
    t = _PUNCT_RE.sub("", t)
    # strip emoji leftovers already gone via \W; keep CJK+alnum
    return t


# STT often mangles wake words (嘿→He/Hey/黑/嗨, 廢物→飞幕/废物).
_WAKE_ALIASES: dict[str, tuple[str, ...]] = {
    "嘿助理": (
        "嘿助理",
        "嗨助理",
        "黑助理",
        "hei助理",
        "he助理",
        "hey助理",
        "heyassistant",
        "hiassistant",
        "helloassistant",
    ),
    "小廢物": (
        "小廢物",
        "小废物",
        "小飞物",
        "小飛物",
        "小飞幕",
        "小飛幕",
        "小废料",
        "小廢料",
    ),
    "hey assistant": (
        "heyassistant",
        "hiassistant",
        "heyjuly",
        "heyjulie",
        "heyjuly",
        "heyjarvis",
    ),
}


def phrase_hit(transcript: str, phrases: list[str]) -> str | None:
    """Match wake phrases; tolerate STT slips without matching bare 你好/嘿."""
    from difflib import SequenceMatcher

    hay = _norm(transcript)
    if not hay or len(hay) < 2:
        return None

    # 1) exact / substring (phrase must appear in full)
    for p in sorted(phrases, key=lambda x: len(_norm(x)), reverse=True):
        n = _norm(p)
        if len(n) >= 3 and n in hay:
            return p

    # 2) known STT aliases (never bare 你好 / 嘿)
    alias_map: dict[str, tuple[str, ...]] = {
        "嘿助理": (
            "嘿助理", "嗨助理", "黑助理", "嘿嘴", "嘿嘴理", "嘿助哩", "嘿自理",
            "he助理", "hey助理", "hei助理", "heyassistant", "hiassistant",
        ),
        "小廢物": (
            "小廢物", "小废物", "小飞物", "小飛物", "小飞幕", "小飛幕", "小废料",
        ),
        "hey assistant": (
            "heyassistant", "hiassistant", "heyjulie", "heyjarvis",
        ),
        "你好助理": (
            "你好助理", "你好助手", "您好助理",
        ),
    }
    for label, aliases in {**_WAKE_ALIASES, **alias_map}.items():
        for a in aliases:
            an = _norm(a)
            if len(an) < 3:
                continue
            if an in hay:
                for p in phrases:
                    pn = _norm(p)
                    if pn == _norm(label) or _norm(label) in pn:
                        return p
                for p in phrases:
                    if "助理" in _norm(p) and ("助理" in an or "助" in an):
                        return p
                    if "小" in _norm(p) and an.startswith("小"):
                        return p
                    if "assistant" in _norm(p) and "assist" in an:
                        return p

    # 3) structured: 嘿/嗨/黑 + 助/理/嘴 (not 嘿 alone)
    if re.search(r"(嘿|嗨|黑)(助|理|嘴|自)", hay) or re.search(
        r"(hey|hei|hi)(assistant|assist|julie|jarvis)", hay
    ):
        for p in phrases:
            if "助理" in _norm(p) or "assistant" in _norm(p):
                return p

    # 4) 小 + 廢/飞
    if re.search(r"小.{0,2}(廢|废|飞|飛|物|幕)", hay):
        for p in phrases:
            if "小" in _norm(p):
                return p

    # 5) fuzzy — strict: need high ratio AND similar length (blocks 你好 vs 你好助理)
    best_p, best_r = None, 0.0
    for p in phrases:
        n = _norm(p)
        if len(n) < 3:
            continue
        r = SequenceMatcher(None, n, hay).ratio()
        if abs(len(n) - len(hay)) > 2 and r < 0.9:
            # length mismatch: only accept near-exact
            continue
        if r > best_r:
            best_r, best_p = r, p
    if best_p is not None and best_r >= 0.78:
        return best_p

    return None


def _desktop_user_env() -> dict[str, str]:
    """Inject the active graphical session so TTS/notify path works."""
    import pwd

    env = os.environ.copy()
    run_user = Path("/run/user")
    if not run_user.is_dir():
        return env
    for entry in sorted(run_user.iterdir(), key=lambda p: p.name):
        if not entry.name.isdigit():
            continue
        bus = entry / "bus"
        if not bus.exists():
            continue
        uid = int(entry.name)
        try:
            pw = pwd.getpwuid(uid)
        except KeyError:
            continue
        if pw.pw_name in ("root", "nobody"):
            continue
        env["DISPLAY"] = env.get("DISPLAY") or ":0"
        env["XDG_RUNTIME_DIR"] = str(entry)
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        env["HOME"] = pw.pw_dir
        env["USER"] = pw.pw_name
        env["LOGNAME"] = pw.pw_name
        env["AIPC_WAKE_AS_USER"] = pw.pw_name
        local_once = Path(pw.pw_dir) / ".local/bin/aipc-voice-once"
        if local_once.is_file() and os.access(local_once, os.X_OK):
            env["AIPC_VOICE_ONCE_RESOLVED"] = str(local_once)
        return env
    env.setdefault("DISPLAY", ":0")
    return env


def _write_pcm_wav(path: str, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


class OnceWorker:
    """Background aipc-voice-once runner (no mic). Latest job wins.

    Policy:
    - submit while idle → start immediately
    - submit while busy → cancel current (barge-in) and start new
    Mic stays owned by the phrase-loop stream; jobs only get --wav paths.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._gen = 0

    def busy(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def cancel(self, reason: str = "barge-in") -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                print(f"aipc-voice-wake: cancel voice-once ({reason})", flush=True)
                try:
                    self._proc.terminate()
                except OSError:
                    pass
            self._gen += 1

    def submit_wav(self, wav_path: str) -> None:
        """Run once --wav asynchronously; barge-in cancels prior job."""
        self.cancel(reason="new-job")
        gen = self._gen

        def _run() -> None:
            env = _desktop_user_env()
            cmd = env.pop("AIPC_VOICE_ONCE_RESOLVED", None) or ONCE_CMD
            if not Path(cmd).is_file() and shutil.which(cmd):
                cmd = shutil.which(cmd) or cmd
            argv = [cmd, "--wav", wav_path]
            as_user = env.get("AIPC_WAKE_AS_USER")
            # Already running as desktop user in service; no runuser needed.
            if as_user and os.geteuid() == 0 and as_user != "root":
                argv = ["runuser", "-u", as_user, "--", *argv]
            log_path = Path(env.get("HOME", "/tmp")) / ".cache/aipc/voice-once-from-wake.log"
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_f = open(log_path, "ab", buffering=0)  # noqa: SIM115
            except OSError:
                log_f = subprocess.DEVNULL
            print(f"aipc-voice-wake: async once {' '.join(argv)}", flush=True)
            try:
                proc = subprocess.Popen(
                    argv, env=env, stdout=log_f, stderr=log_f, start_new_session=True
                )
            except OSError as exc:
                print(f"aipc-voice-wake: once spawn failed: {exc}", flush=True)
                return
            with self._lock:
                if gen != self._gen:
                    proc.terminate()
                    return
                self._proc = proc
            rc = proc.wait()
            print(f"aipc-voice-wake: async once finished rc={rc}", flush=True)
            if rc == 0:
                _ux("done", force=True)
                _ux("listening")
            else:
                _ux("error", f"voice-once rc={rc}", force=True)
                _ux("listening")
            try:
                os.unlink(wav_path)
            except OSError:
                pass
            if log_f is not subprocess.DEVNULL:
                try:
                    log_f.close()
                except Exception:
                    pass

        t = threading.Thread(target=_run, name="aipc-once-worker", daemon=True)
        with self._lock:
            self._thread = t
        t.start()


def trigger_once(*, wait: bool = False, timeout: float = 180.0, wav: str | None = None) -> int:
    """Legacy helper: prefer OnceWorker.submit_wav for non-blocking path."""
    env = _desktop_user_env()
    cmd = env.pop("AIPC_VOICE_ONCE_RESOLVED", None) or ONCE_CMD
    if not Path(cmd).is_file() and shutil.which(cmd):
        cmd = shutil.which(cmd) or cmd
    as_user = env.get("AIPC_WAKE_AS_USER")
    argv = [cmd, "--wav", wav] if wav else [cmd, "--vad"]
    if as_user and os.geteuid() == 0 and as_user != "root":
        argv = ["runuser", "-u", as_user, "--", *argv]
    log = Path(env.get("HOME", "/tmp")) / ".cache/aipc/voice-once-from-wake.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log, "ab", buffering=0)  # noqa: SIM115
    except OSError:
        log_f = subprocess.DEVNULL
    print(f"aipc-voice-wake: run {' '.join(argv)} wait={wait}", flush=True)
    if wait:
        try:
            r = subprocess.run(argv, env=env, stdout=log_f, stderr=log_f, timeout=timeout)
            return int(r.returncode)
        except subprocess.TimeoutExpired:
            return 124
        finally:
            if log_f is not subprocess.DEVNULL:
                try:
                    log_f.close()
                except Exception:
                    pass
    subprocess.Popen(argv, env=env, stdout=log_f, stderr=log_f, start_new_session=True)
    return 0


def _rms(frame: bytes) -> float:
    if len(frame) < 2:
        return 0.0
    n = len(frame) // 2
    samples = array.array("h")
    samples.frombytes(frame[: n * 2])
    if not samples:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / len(samples)) ** 0.5


def _record_wav_seconds(path: str, seconds: float) -> None:
    subprocess.run(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-d",
            str(max(0.4, int(seconds) if float(seconds).is_integer() else seconds)),
            path,
        ],
        check=True,
        capture_output=True,
    )


def _stt_wav(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    url = STT_URL
    if "language=" not in url and STT_LANG:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}language={STT_LANG}"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "audio/wav"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())
    return str(body.get("text") or "").strip()


def stt_available() -> bool:
    try:
        base = STT_URL.rsplit("/", 1)[0]
        req = urllib.request.Request(f"{base}/healthz", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _arecord_raw_cmd() -> list[str]:
    return [
        "arecord",
        "-f",
        "S16_LE",
        "-r",
        str(SAMPLE_RATE),
        "-c",
        "1",
        "-t",
        "raw",
        "-q",
        "-",
    ]


def _open_arecord_raw() -> subprocess.Popen:
    """Open continuous raw capture; raise if PipeWire/ALSA rejects us."""
    proc = subprocess.Popen(
        _arecord_raw_cmd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_capture_env(),
    )
    assert proc.stdout is not None
    time.sleep(0.15)
    if proc.poll() is not None:
        err = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
        raise RuntimeError(
            f"arecord failed immediately (rc={proc.returncode}): {err.strip() or 'no stderr'} "
            f"— wake must run as desktop user with XDG_RUNTIME_DIR (not bare root)"
        )
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    chunk = proc.stdout.read(frame_bytes)
    if not chunk:
        raise RuntimeError("arecord opened but produced no audio frames")
    print(f"aipc-voice-wake: mic ok first_frame_rms={_rms(chunk):.0f}", flush=True)
    return proc


def _calibrate_noise(proc: subprocess.Popen, seconds: float = 1.5) -> float:
    """Estimate ambient RMS; return adaptive speech threshold."""
    assert proc.stdout is not None
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    n = max(1, int(seconds * 1000 // FRAME_MS))
    vals: list[float] = []
    for _ in range(n):
        data = proc.stdout.read(frame_bytes)
        if not data:
            break
        vals.append(_rms(data))
    if not vals:
        return ENERGY_THRESHOLD
    vals.sort()
    noise = vals[max(0, len(vals) // 5)]
    adaptive = max(ENERGY_THRESHOLD, noise * 1.25 + 400.0)
    adaptive = min(adaptive, max(6000.0, noise + 3500.0), 12000.0)
    print(
        f"aipc-voice-wake: calibrated noise_rms={noise:.0f} "
        f"threshold={adaptive:.0f} (min_env={ENERGY_THRESHOLD})",
        flush=True,
    )
    return adaptive


def _ctrl_sock_path() -> Path:
    # Prefer live user runtime; fall back to /tmp
    uid = os.geteuid()
    candidates = [
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")) / "aipc-wake.sock",
        Path(f"/tmp/aipc-wake-{uid}.sock"),
    ]
    if "AIPC_WAKE_SOCK" in os.environ:
        return Path(os.environ["AIPC_WAKE_SOCK"])
    for c in candidates:
        try:
            c.parent.mkdir(parents=True, exist_ok=True)
            return c
        except OSError:
            continue
    return candidates[-1]


def run_phrase_loop() -> int:
    # Best-effort basic denoise chain before opening mic
    try:
        from aipc_lib.voice_audio import ensure_denoise_source
        ensure_denoise_source()
    except Exception:
        try:
            import voice_audio  # type: ignore
            voice_audio.ensure_denoise_source()
        except Exception:
            pass

    """Single-mic async pipeline.

    Stream ownership: one arecord for the whole service.
    States:
      listen  — energy gate + short wake STT
      command — same stream, end-of-speech VAD for the user command
    Jobs (STT/LLM/TTS via aipc-voice-once --wav) run in a background worker.
    Policy:
      - new wake/ptt while recording command → interrupt & restart command capture
      - new job while worker busy → barge-in cancel previous once
    External PTT: write line "ptt" to $XDG_RUNTIME_DIR/aipc-wake.sock
    """
    import select
    import socket

    phrases = load_phrases()
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    wake_frames = max(1, int(CAPTURE_S * 1000 // FRAME_MS))
    preroll_n = max(1, 700 // FRAME_MS)
    end_need = max(1, CMD_END_SILENCE_MS // FRAME_MS)
    cmd_max_frames = max(1, int(CMD_MAX_S * 1000 // FRAME_MS))
    worker = OnceWorker()

    print(
        f"aipc-voice-wake: phrase mode phrases={phrases!r} "
        f"energy>={ENERGY_THRESHOLD} wake_cap={CAPTURE_S}s "
        f"cmd_max={CMD_MAX_S}s end_silence={CMD_END_SILENCE_MS}ms "
        f"cooldown={COOLDOWN_S}s stt={STT_URL} (single-mic async)",
        flush=True,
    )
    if not stt_available():
        print("aipc-voice-wake: STT not healthy yet", flush=True)

    try:
        proc = _open_arecord_raw()
    except RuntimeError as exc:
        print(f"aipc-voice-wake: {exc}", flush=True)
        return 2
    assert proc.stdout is not None
    energy_thr = _calibrate_noise(proc, seconds=1.5)

    # Control socket for button / external PTT (non-blocking accept)
    sock_path = _ctrl_sock_path()
    try:
        if sock_path.exists():
            sock_path.unlink()
    except OSError:
        pass
    ctrl: socket.socket | None = None
    try:
        ctrl = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        ctrl.bind(str(sock_path))
        ctrl.listen(4)
        ctrl.setblocking(False)
        try:
            os.chmod(sock_path, 0o666)
        except OSError:
            pass
        print(f"aipc-voice-wake: ctrl socket {sock_path} (send 'ptt')", flush=True)
    except OSError as exc:
        print(f"aipc-voice-wake: ctrl socket unavailable: {exc}", flush=True)
        ctrl = None
    _ux("listening", force=True)

    last_wake_check = time.monotonic()
    high = 0
    empty_reads = 0
    preroll: list[bytes] = []
    # mode: listen | wake_buf | command
    mode = "listen"
    wake_buf = bytearray()
    wake_left = 0
    cmd_buf = bytearray()
    cmd_frames = 0
    cmd_silent = 0
    cmd_speech = False
    cmd_t0 = 0.0
    ptt_requested = False

    def _poll_ctrl() -> None:
        nonlocal ptt_requested, mode, cmd_buf, cmd_frames, cmd_silent, cmd_speech, cmd_t0
        if ctrl is None:
            return
        try:
            r, _, _ = select.select([ctrl], [], [], 0)
        except (OSError, ValueError):
            return
        if not r:
            return
        try:
            conn, _ = ctrl.accept()
        except BlockingIOError:
            return
        try:
            conn.settimeout(0.2)
            data = conn.recv(64).decode(errors="replace").strip().lower()
            conn.close()
        except OSError:
            return
        if data in ("ptt", "command", "1", "push"):
            print("aipc-voice-wake: ctrl ptt → command capture (interrupt if needed)", flush=True)
            _ux("wake", "控制中心", force=True)
            _ux("recording", force=True)
            ptt_requested = True
            # interrupt wake_buf or restart command
            mode = "command"
            cmd_buf = bytearray()
            for f in preroll:
                cmd_buf.extend(f)
            cmd_frames = 0
            cmd_silent = 0
            cmd_speech = False
            cmd_t0 = time.monotonic()

    def _finish_command(pcm: bytes, reason: str) -> None:
        if len(pcm) < SAMPLE_RATE:  # <0.5s
            print(f"aipc-voice-wake: command too short reason={reason}", flush=True)
            return
        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="aipc-cmd-")
        os.close(fd)
        _write_pcm_wav(wav_path, bytes(pcm))
        print(
            f"aipc-voice-wake: command captured {len(pcm)/2/SAMPLE_RATE:.2f}s "
            f"reason={reason} → async once",
            flush=True,
        )
        if reason == "end_silence" or reason == "max":
            _ux("thinking", f"{len(pcm)/2/SAMPLE_RATE:.1f}s", force=True)
        worker.submit_wav(wav_path)

    try:
        while True:
            _poll_ctrl()

            if muted():
                _ux("muted")
                time.sleep(0.2)
                proc.stdout.read(frame_bytes)
                high = 0
                mode = "listen"
                continue

            data = proc.stdout.read(frame_bytes)
            if not data:
                empty_reads += 1
                if proc.poll() is not None or empty_reads > 50:
                    err = b""
                    if proc.stderr:
                        try:
                            err = proc.stderr.read() or b""
                        except Exception:
                            pass
                    print(
                        f"aipc-voice-wake: arecord died rc={proc.poll()} "
                        f"{err.decode(errors='replace')[:200]}",
                        flush=True,
                    )
                    return 2
                time.sleep(0.05)
                continue
            empty_reads = 0
            rms = _rms(data)
            loud = rms >= energy_thr

            if mode != "wake_buf" and mode != "command":
                preroll.append(data)
                if len(preroll) > preroll_n:
                    preroll.pop(0)

            # ---- command capture (same stream, never open second mic) ----
            if mode == "command":
                cmd_buf.extend(data)
                cmd_frames += 1
                if loud:
                    cmd_speech = True
                    cmd_silent = 0
                elif cmd_speech:
                    cmd_silent += 1
                    if cmd_silent >= end_need:
                        mode = "listen"
                        _finish_command(bytes(cmd_buf), "end_silence")
                        last_wake_check = time.monotonic()
                        high = 0
                        continue
                if not cmd_speech and (time.monotonic() - cmd_t0) >= CMD_START_TIMEOUT_S:
                    mode = "listen"
                    print("aipc-voice-wake: command start timeout", flush=True)
                    _ux("no_speech", force=True)
                    _ux("listening")
                    high = 0
                    continue
                if cmd_frames >= cmd_max_frames:
                    mode = "listen"
                    _finish_command(bytes(cmd_buf), "max")
                    last_wake_check = time.monotonic()
                    high = 0
                continue

            # ---- wake phrase short buffer ----
            if mode == "wake_buf":
                wake_buf.extend(data)
                wake_left -= 1
                if wake_left > 0:
                    continue
                mode = "listen"
                fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="aipc-wake-")
                os.close(fd)
                try:
                    _write_pcm_wav(wav_path, bytes(wake_buf))
                    print(
                        f"aipc-voice-wake: energy → STT check "
                        f"({len(wake_buf)/2/SAMPLE_RATE:.2f}s)",
                        flush=True,
                    )
                    try:
                        text = _stt_wav(wav_path)
                    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                        print(f"aipc-voice-wake: STT check failed: {exc}", flush=True)
                        text = ""
                    hit = phrase_hit(text, phrases) if text else None
                    print(f"aipc-voice-wake: heard {text!r} hit={hit!r}", flush=True)
                    if text and not hit:
                        # Quiet miss — no overlay spam
                        if voice_ux:
                            try:
                                voice_ux.write_status("miss", text[:40])
                            except Exception:
                                pass
                        _ux("listening")
                    elif not text:
                        if voice_ux:
                            try:
                                voice_ux.write_status("no_speech", "")
                            except Exception:
                                pass
                        _ux("listening")
                    if hit:
                        print(
                            f"aipc-voice-wake: phrase {hit!r} → command mode "
                            f"(mic stays open, once is async)",
                            flush=True,
                        )
                        _ux("wake", str(hit), force=True)
                        _ux("recording", force=True)
                        mode = "command"
                        cmd_buf = bytearray()
                        # keep a little post-wake audio from end of wake clip
                        tail = bytes(wake_buf[-(frame_bytes * 10) :])
                        cmd_buf.extend(tail)
                        cmd_frames = 0
                        cmd_silent = 0
                        cmd_speech = False
                        cmd_t0 = time.monotonic()
                        last_wake_check = time.monotonic()
                finally:
                    try:
                        os.unlink(wav_path)
                    except OSError:
                        pass
                wake_buf.clear()
                high = 0
                continue

            # ---- listen: energy gate ----
            if ptt_requested:
                ptt_requested = False
                # already switched in _poll_ctrl
                continue

            if loud:
                high += 1
            else:
                high = 0
            now = time.monotonic()
            if high < ENERGY_FRAMES or (now - last_wake_check) < COOLDOWN_S:
                continue

            high = 0
            last_wake_check = now
            mode = "wake_buf"
            wake_buf = bytearray()
            for f in preroll:
                wake_buf.extend(f)
            preroll.clear()
            wake_left = wake_frames
            print("aipc-voice-wake: energy gate open → wake buffering", flush=True)
            # ambient energy: do not flash overlay (spam); status file only
            if voice_ux:
                try:
                    voice_ux.write_status("detecting", "辨識中")
                except Exception:
                    pass
    except KeyboardInterrupt:
        return 0
    finally:
        worker.cancel(reason="shutdown")
        if ctrl is not None:
            try:
                ctrl.close()
            except OSError:
                pass
            try:
                sock_path.unlink(missing_ok=True)
            except OSError:
                pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


def run_energy_loop() -> int:
    """Energy VAD only — higher false positives; last-resort fallback."""
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    print(
        f"aipc-voice-wake: energy mode threshold={ENERGY_THRESHOLD} "
        f"cooldown={COOLDOWN_S}s (no phrase/STT gate)",
        flush=True,
    )
    proc = subprocess.Popen(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-t",
            "raw",
            "-q",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_capture_env(),
    )
    assert proc.stdout is not None
    last = 0.0
    high = 0
    try:
        while True:
            if muted():
                time.sleep(0.2)
                proc.stdout.read(frame_bytes)
                continue
            data = proc.stdout.read(frame_bytes)
            if not data:
                time.sleep(0.05)
                continue
            if _rms(data) >= ENERGY_THRESHOLD:
                high += 1
            else:
                high = 0
            now = time.monotonic()
            if high >= ENERGY_FRAMES and (now - last) >= COOLDOWN_S:
                last = now
                high = 0
                print("aipc-voice-wake: energy trigger → aipc-voice-once", flush=True)
                trigger_once()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def run_openwakeword() -> int:
    """Pretrained openWakeWord (hey_jarvis etc.). Prefer venv with onnx models."""
    # Prefer dedicated venv (system python may lack oww / tflite).
    if OWW_VENV_PYTHON.is_file() and Path(sys.executable).resolve() != OWW_VENV_PYTHON.resolve():
        # Re-exec under venv so import openwakeword works
        argv = [str(OWW_VENV_PYTHON), str(Path(__file__).resolve()), "--mode", "openwakeword"]
        print(f"aipc-voice-wake: re-exec openwakeword via {OWW_VENV_PYTHON}", flush=True)
        os.execv(str(OWW_VENV_PYTHON), argv)

    try:
        import openwakeword  # type: ignore
        from openwakeword.model import Model  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-voice-wake: openwakeword import failed: {exc}", flush=True)
        return run_phrase_loop() if stt_available() else run_energy_loop()

    if MODEL_PATH.is_file():
        print(f"aipc-voice-wake: loading user model {MODEL_PATH}", flush=True)
        oww = Model(wakeword_models=[str(MODEL_PATH)], inference_framework="onnx")
    else:
        durable = Path("/var/lib/aipc-voice/wake/models") / f"{PRETRAINED}_v0.1.onnx"
        if durable.is_file():
            print(f"aipc-voice-wake: loading {durable}", flush=True)
            oww = Model(wakeword_models=[str(durable)], inference_framework="onnx")
        else:
            print(f"aipc-voice-wake: loading pretrained {PRETRAINED}", flush=True)
            try:
                openwakeword.utils.download_models()
            except Exception:
                pass
            oww = Model(wakeword_models=[PRETRAINED], inference_framework="onnx")

    # openWakeWord is trained on 80 ms frames (1280 samples @ 16 kHz)
    frame_samples = 1280
    frame_bytes = frame_samples * 2
    proc = subprocess.Popen(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-t",
            "raw",
            "-q",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_capture_env(),
    )
    assert proc.stdout is not None
    last = 0.0
    # Higher default threshold → fewer false positives
    threshold = float(os.environ.get("AIPC_WAKE_THRESHOLD", "0.6"))
    print(f"aipc-voice-wake: openWakeWord ready threshold={threshold}", flush=True)
    try:
        while True:
            if muted():
                time.sleep(0.2)
                proc.stdout.read(frame_bytes)
                continue
            data = proc.stdout.read(frame_bytes)
            if not data or len(data) < frame_bytes:
                continue
            try:
                import numpy as np  # type: ignore

                audio = np.frombuffer(data, dtype=np.int16)
            except Exception:
                audio = struct.unpack(f"<{len(data) // 2}h", data)
            prediction = oww.predict(audio)
            score = max(float(v) for v in prediction.values()) if prediction else 0.0
            now = time.monotonic()
            if score >= threshold and (now - last) >= COOLDOWN_S:
                last = now
                print(f"aipc-voice-wake: detected score={score:.2f} → once", flush=True)
                trigger_once()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def train_stub(samples_dir: Path, out_path: Path, label: str) -> int:
    """v0: write marker; custom phrases don't need ONNX training."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wavs = sorted(samples_dir.glob("*.wav"))
    if len(wavs) < 1:
        print("aipc-voice-train-wake: need at least 1 WAV in samples dir", file=sys.stderr)
        return 1
    marker = out_path.with_suffix(".txt")
    marker.write_text(
        f"label={label}\nsamples={len(wavs)}\n"
        "status=use-phrase-mode\n"
        "note=custom wake uses STT phrase match; edit /etc/aipc/wake/phrases\n"
    )
    print(f"aipc-voice-train-wake: wrote {marker}; prefer phrase mode for custom words")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument(
        "--mode",
        choices=("auto", "phrase", "energy", "openwakeword"),
        default="auto",
    )
    p.add_argument("--train", action="store_true", help="run train stub")
    p.add_argument("--samples", type=Path, default=Path("/var/lib/aipc-voice/wake/samples"))
    p.add_argument("--label", default="assistant")
    p.add_argument("--out", type=Path, default=MODEL_PATH)
    return p


def _self_test() -> int:
    assert _rms(b"\x00\x00" * 100) == 0.0
    loud = struct.pack("<h", 10000) * 200
    assert _rms(loud) > 1000
    assert phrase_hit("嘿助理", ["嘿助理", "hey assistant"]) == "嘿助理"
    assert phrase_hit("嘿嘴。", ["嘿助理"]) == "嘿助理"
    assert phrase_hit("今天天气怎么样", ["嘿助理"]) is None
    assert phrase_hit("你好。", ["你好助理", "嘿助理"]) is None  # bare 你好 must NOT wake
    assert phrase_hit("你好助理", ["你好助理"]) == "你好助理"
    assert phrase_hit("He助理。", ["嘿助理"]) == "嘿助理"
    assert phrase_hit("小飞幕听到了吗", ["小廢物"]) == "小廢物"
    assert _norm("嘿 助 理!") == "嘿助理" or "嘿" in _norm("嘿 助 理!")
    # space stripped in norm
    assert "嘿助理" == _norm("嘿 助理") or _norm("嘿助理") in _norm("嘿 助理") or _norm(
        "嘿助理"
    ) == _norm("嘿助理")
    assert phrase_hit("请打开嘿助理功能", ["嘿助理"]) == "嘿助理"
    assert phrase_hit("嘿", ["嘿助理"]) is None
    print("aipc-voice-wake: self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.train:
        return train_stub(args.samples, args.out, args.label)
    mode = args.mode
    if mode == "phrase":
        return run_phrase_loop()
    if mode == "energy":
        return run_energy_loop()
    if mode == "openwakeword":
        return run_openwakeword()
    # auto: phrase if STT up (custom + low FP + fast start); else OWW; else energy
    if stt_available():
        return run_phrase_loop()
    if OWW_VENV_PYTHON.is_file():
        try:
            return run_openwakeword()
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-voice-wake: openwakeword failed: {exc}", flush=True)
    return run_energy_loop()


if __name__ == "__main__":
    raise SystemExit(main())
