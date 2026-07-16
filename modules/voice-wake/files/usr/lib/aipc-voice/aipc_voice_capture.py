"""Mic capture + progressive STT helpers for voice-wake (no session policy)."""
from __future__ import annotations

import array
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

from aipc_voice_wake_policy import ENERGY_THRESHOLD, FRAME_MS, SAMPLE_RATE

PARTIAL_STT_S = float(os.environ.get("AIPC_WAKE_PARTIAL_STT_S", "0.9"))
PARTIAL_STT_MIN_S = float(os.environ.get("AIPC_WAKE_PARTIAL_STT_MIN_S", "0.7"))
STT_URL = os.environ.get("AIPC_VOICE_STT_URL", "http://127.0.0.1:9001/transcribe")
STT_LANG = os.environ.get("AIPC_WAKE_STT_LANG", "zh")

_JUNK_PARTICLES = frozenset(
    {
        "我",
        "嗯",
        "啊",
        "呃",
        "哦",
        "喔",
        "呀",
        "的",
        "了",
        "吗",
        "呢",
        "吧",
        "哈",
        "嘿",
        "唔",
        "恩",
        "那个",
        "就是",
    }
)

try:
    import aipc_voice_ux as voice_ux  # type: ignore
except Exception:
    voice_ux = None


def capture_env() -> dict:
    """Mic env for wake arecord — basic RNNoise denoise by default."""
    env = os.environ.copy()
    if os.environ.get("AIPC_WAKE_DENOISE", "1") == "0":
        env.pop("PULSE_SOURCE", None)
        return env
    try:
        from aipc_lib.voice_audio import capture_env as _ce, ensure_denoise_source

        ensure_denoise_source()
        return _ce(env)
    except Exception as exc:
        print(f"aipc-voice-capture: denoise via aipc_lib failed: {exc}", flush=True)
    try:
        import voice_audio  # type: ignore

        voice_audio.ensure_denoise_source()
        return voice_audio.capture_env(env)
    except Exception as exc:
        print(f"aipc-voice-capture: denoise via voice_audio failed: {exc}", flush=True)
    env.setdefault("PULSE_SOURCE", "aipc_denoise_out.monitor")
    return env


def write_pcm_wav(path: str, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def rms(frame: bytes) -> float:
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


def progressive_core(text: str) -> str:
    s = (text or "").strip()
    return re.sub(
        r"[\s\W_😔😊😂😅…·。！？!?，,、；;：:\"'“”‘’]+",
        "",
        s,
        flags=re.UNICODE,
    )


def progressive_usable(text: str) -> bool:
    core = progressive_core(text)
    if len(core) < 2:
        return False
    if core in _JUNK_PARTICLES:
        return False
    cjk = sum(1 for c in core if "一" <= c <= "鿿")
    if cjk >= 2:
        return True
    alnum = sum(1 for c in core if c.isalnum())
    return alnum >= 3


def progressive_looks_complete(text: str) -> bool:
    core = progressive_core(text)
    if len(core) < 5:
        return False
    raw = (text or "").strip()
    if any(raw.endswith(x) for x in ("？", "?", "！", "!", "吗", "呢", "吧", "啊")):
        return len(core) >= 3
    trailers = (
        "的",
        "了",
        "是",
        "在",
        "和",
        "跟",
        "与",
        "把",
        "被",
        "就",
        "还",
        "會",
        "会",
        "要",
        "想",
        "能",
        "可",
        "对",
        "對",
        "给",
        "給",
        "从",
        "從",
        "到",
        "比",
        "那",
        "这",
        "這",
        "我",
        "你",
        "他",
        "她",
        "它",
        "们",
        "們",
    )
    for t in trailers:
        if core.endswith(t):
            return False
    if len(core) < 8:
        return False
    return True


def stt_wav(path: str) -> str:
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


def arecord_raw_cmd() -> list[str]:
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


def open_arecord_raw() -> subprocess.Popen:
    proc = subprocess.Popen(
        arecord_raw_cmd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=capture_env(),
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
    print(f"aipc-voice-wake: mic ok first_frame_rms={rms(chunk):.0f}", flush=True)
    return proc


def calibrate_noise(proc: subprocess.Popen, seconds: float = 1.5) -> float:
    assert proc.stdout is not None
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    n = max(1, int(seconds * 1000 // FRAME_MS))
    vals: list[float] = []
    for _ in range(n):
        data = proc.stdout.read(frame_bytes)
        if not data:
            break
        vals.append(rms(data))
    if not vals:
        return ENERGY_THRESHOLD
    vals.sort()
    noise = vals[max(0, len(vals) // 5)]
    ratio = float(os.environ.get("AIPC_WAKE_CALIB_RATIO", "1.15"))
    offset = float(os.environ.get("AIPC_WAKE_CALIB_OFFSET", "100.0"))
    adaptive = max(ENERGY_THRESHOLD, noise * ratio + offset)
    adaptive = min(adaptive, max(4000.0, noise + 1800.0), 8000.0)
    print(
        f"aipc-voice-wake: calibrated noise_rms={noise:.0f} "
        f"threshold={adaptive:.0f} (min_env={ENERGY_THRESHOLD})",
        flush=True,
    )
    return adaptive


def record_wav_seconds(path: str, seconds: float) -> None:
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
        env=capture_env(),
    )


class PartialSttWorker:
    """Background STT snapshots while the user is still talking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._busy = False
        self._gen = 0
        self._pending: bytes | None = None

    def reset(self) -> None:
        with self._lock:
            self._gen += 1
            self._text = ""
            self._pending = None
            self._busy = False

    def get_text(self) -> str:
        with self._lock:
            return self._text

    def request(self, pcm: bytes) -> None:
        if len(pcm) < int(SAMPLE_RATE * PARTIAL_STT_MIN_S) * 2:
            return
        with self._lock:
            if self._busy:
                self._pending = bytes(pcm)
                return
            self._busy = True
            gen = self._gen
            snap = bytes(pcm)

        def _run() -> None:
            nonlocal snap, gen
            while True:
                text = ""
                fd, path = tempfile.mkstemp(suffix=".wav", prefix="aipc-partial-")
                os.close(fd)
                try:
                    write_pcm_wav(path, snap)
                    text = stt_wav(path)
                except Exception as exc:  # noqa: BLE001
                    print(f"aipc-voice-wake: partial STT fail: {exc}", flush=True)
                    text = ""
                finally:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                with self._lock:
                    if gen != self._gen:
                        self._busy = False
                        self._pending = None
                        return
                    if text and text.strip():
                        self._text = text.strip()
                        show = self._text
                    else:
                        show = self._text
                    pending = self._pending
                    self._pending = None
                    if pending is None:
                        self._busy = False
                        if show:
                            if voice_ux:
                                try:
                                    voice_ux.write_status(
                                        "recording", "", partial=show[:120]
                                    )
                                except Exception:
                                    pass
                            print(
                                f"aipc-voice-wake: partial STT: {show[:80]!r}",
                                flush=True,
                            )
                        return
                    snap = pending

        threading.Thread(target=_run, name="aipc-partial-stt", daemon=True).start()


# Legacy aliases for wake.py
_capture_env = capture_env
_write_pcm_wav = write_pcm_wav
_rms = rms
_progressive_core = progressive_core
_progressive_usable = progressive_usable
_progressive_looks_complete = progressive_looks_complete
_stt_wav = stt_wav
_arecord_raw_cmd = arecord_raw_cmd
_open_arecord_raw = open_arecord_raw
_calibrate_noise = calibrate_noise
_record_wav_seconds = record_wav_seconds
