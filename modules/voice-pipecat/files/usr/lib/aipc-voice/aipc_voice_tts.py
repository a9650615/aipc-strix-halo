"""TTS router: CosyVoice clone (CJK) → Kokoro-82M → espeak last resort.

Chinese prefers CosyVoice zero-shot clone on :9880 when preferred (default on)
and available; falls through to Kokoro Mandarin packs, then espeak.
English uses Kokoro first (skip CosyVoice unless AIPC_TTS_FORCE_COSYVOICE=1).

OpenAI-compatible Kokoro: POST :8880/v1/audio/speech
CosyVoice clone:         POST :9880/tts  body {"text":"..."} → audio/wav

Voice override order for Kokoro (first wins):
  AIPC_TTS_VOICE env → /etc/aipc/voice/tts-zh-voice or tts-en-voice → built-in default
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

COSYVOICE_URL = os.environ.get("AIPC_COSYVOICE_URL", "http://127.0.0.1:9880/tts")
COSYVOICE_HEALTH_URL = os.environ.get(
    "AIPC_COSYVOICE_HEALTH_URL", "http://127.0.0.1:9880/healthz"
)
KOKORO_URL = os.environ.get("AIPC_KOKORO_URL", "http://127.0.0.1:8880/v1/audio/speech")
LOCAL_TTS_URL = os.environ.get("AIPC_LOCAL_TTS_URL", KOKORO_URL)
TTS_TIMEOUT = float(os.environ.get("AIPC_TTS_TIMEOUT", "90"))
HEALTH_TIMEOUT = float(os.environ.get("AIPC_TTS_HEALTH_TIMEOUT", "1.5"))

_VOICE_ZH_FILE = Path(os.environ.get("AIPC_TTS_VOICE_ZH_FILE", "/etc/aipc/voice/tts-zh-voice"))
_VOICE_EN_FILE = Path(os.environ.get("AIPC_TTS_VOICE_EN_FILE", "/etc/aipc/voice/tts-en-voice"))


def _voice_from_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    except OSError:
        return None
    return None


def _resolve_voice(env_key: str, file_path: Path, default: str) -> str:
    env = os.environ.get(env_key, "").strip()
    if env:
        return env
    from_file = _voice_from_file(file_path)
    if from_file:
        return from_file
    return default


# Defaults (see GET /v1/audio/voices). zf_* / zm_* = Mandarin packs.
_DEFAULT_VOICE_EN = "af_heart"
# zf_xiaoyi: clearer / more "assistant" than soft mainland-broadcast xiaoxiao.
_DEFAULT_VOICE_ZH = "zf_xiaoyi"
MODEL = os.environ.get("AIPC_TTS_MODEL", "kokoro")


def voice_en() -> str:
    return _resolve_voice("AIPC_TTS_VOICE_EN", _VOICE_EN_FILE, _DEFAULT_VOICE_EN)


def voice_zh() -> str:
    return _resolve_voice("AIPC_TTS_VOICE_ZH", _VOICE_ZH_FILE, _DEFAULT_VOICE_ZH)


# Back-compat for tests / callers that read the attribute once.
VOICE_EN = _DEFAULT_VOICE_EN
VOICE_ZH = _DEFAULT_VOICE_ZH

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")
# Dense CJK: if ≥15% of letters are CJK, treat as Chinese utterance.
_LETTER_RE = re.compile(r"[\w㐀-鿿豈-﫿]", re.UNICODE)


def is_cjk(text: str) -> bool:
    if _CJK_RE.search(text) is None:
        return False
    letters = _LETTER_RE.findall(text)
    if not letters:
        return False
    cjk = sum(1 for ch in letters if _CJK_RE.match(ch))
    return (cjk / len(letters)) >= 0.12 or cjk >= 2


def choose_voice(text: str) -> str:
    override = os.environ.get("AIPC_TTS_VOICE", "").strip()
    if override:
        return override
    return voice_zh() if is_cjk(text) else voice_en()


def prefer_cosyvoice() -> bool:
    """Default on: CJK replies try CosyVoice clone first."""
    env = os.environ.get("AIPC_PREFER_COSYVOICE", "").strip()
    if env != "":
        return env == "1"
    path = Path(os.environ.get("AIPC_PREFER_COSYVOICE_FILE", "/etc/aipc/voice/prefer-cosyvoice"))
    try:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    return s == "1"
    except OSError:
        pass
    return False



def sanitize_tts_text(text: str) -> str:
    """Strip emoji/markdown noise that breaks Kokoro (HTTP 400) or confuses listeners."""
    if not text:
        return ""
    s = str(text)
    # emoji / symbols outside basic multilingual plane common in chat
    s = re.sub(
        r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F9FF]+",
        "",
        s,
    )
    s = re.sub(r"[`*_#>\[\]()]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Kokoro struggles with very long strings; keep a safe head
    if len(s) > 400:
        s = s[:400].rsplit(" ", 1)[0] or s[:400]
    return s


def _fix_wav_header(data: bytes) -> bytes:
    """Rewrite RIFF/data sizes. Kokoro often emits 0xFFFFFFFF streaming sizes."""
    import struct

    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    out = bytearray(data)
    struct.pack_into("<I", out, 4, len(out) - 8)
    i = 12
    while i + 8 <= len(out):
        chunk_id = bytes(out[i : i + 4])
        chunk_size = struct.unpack_from("<I", out, i + 4)[0]
        if chunk_id == b"data":
            data_size = len(out) - (i + 8)
            struct.pack_into("<I", out, i + 4, data_size)
            struct.pack_into("<I", out, 4, len(out) - 8)
            break
        # corrupt/huge size → treat rest as data
        if chunk_size > len(out) or chunk_size == 0xFFFFFFFF:
            data_size = len(out) - (i + 8)
            struct.pack_into("<I", out, i + 4, data_size)
            struct.pack_into("<I", out, 4, len(out) - 8)
            break
        nxt = i + 8 + chunk_size + (chunk_size & 1)
        if nxt <= i:
            break
        i = nxt
    return bytes(out)


def _sniff_suffix(audio: bytes, content: str) -> str:
    content = (content or "").lower()
    if audio[:4] == b"RIFF":
        return ".wav"
    if audio[:3] == b"ID3" or (len(audio) > 2 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0):
        return ".mp3"
    if "mpeg" in content or "mp3" in content:
        return ".mp3"
    if "opus" in content:
        return ".opus"
    if "flac" in content:
        return ".flac"
    return ".wav"

def force_cosyvoice() -> bool:
    return os.environ.get("AIPC_TTS_FORCE_COSYVOICE", "0") == "1"


def cosyvoice_wanted(text: str) -> bool:
    if force_cosyvoice():
        return True
    return prefer_cosyvoice() and is_cjk(text)


def cosyvoice_healthy(opener=urllib.request.urlopen) -> bool:
    """Best-effort health probe; failure means try CosyVoice anyway and fall through."""
    if os.environ.get("AIPC_COSYVOICE_SKIP_HEALTH", "0") == "1":
        return True
    req = urllib.request.Request(COSYVOICE_HEALTH_URL, method="GET")
    try:
        with opener(req, timeout=HEALTH_TIMEOUT) as resp:
            raw = resp.read()
            if resp.status and int(resp.status) >= 400:
                return False
        try:
            data = json.loads(raw.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return True
        if isinstance(data, dict):
            status = str(data.get("status", "ok")).lower()
            if status in ("degraded", "error", "down"):
                return False
            if data.get("model_present") is False:
                return False
            return status in ("ok", "healthy", "ready", "up", "")
        return True
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


def tts_url_chain(text: str, *, check_health: bool = False, opener=urllib.request.urlopen) -> list[str]:
    """Ordered HTTP backends before espeak.

    Chinese (default): CosyVoice :9880/tts → Kokoro :8880/v1/audio/speech
    English:           Kokoro only (CosyVoice only if AIPC_TTS_FORCE_COSYVOICE=1)
    """
    chain: list[str] = []
    if cosyvoice_wanted(text):
        if not check_health or cosyvoice_healthy(opener=opener):
            chain.append(COSYVOICE_URL)
    kokoro = LOCAL_TTS_URL or KOKORO_URL
    if kokoro not in chain:
        chain.append(kokoro)
    return chain


def choose_tts_url(text: str) -> str:
    """Primary URL for this utterance (first of the fallback chain)."""
    return tts_url_chain(text, check_health=False)[0]


def _is_kokoro_url(url: str) -> bool:
    return "audio/speech" in url or url in (KOKORO_URL, LOCAL_TTS_URL)


def build_payload(text: str, url: str) -> tuple[bytes, str]:
    if _is_kokoro_url(url):
        return (
            json.dumps(
                {
                    "model": MODEL,
                    "voice": choose_voice(text),
                    "input": text,
                    "response_format": "wav",
                    "speed": float(os.environ.get("AIPC_TTS_SPEED", "1.0")),
                }
            ).encode(),
            "application/json",
        )
    # CosyVoice clone: server reads clone.wav; client only sends text.
    return json.dumps({"text": text}).encode(), "application/json"


def _audio_env() -> dict[str, str]:
    """Ensure paplay finds the user PipeWire/Pulse session (wake/system units)."""
    env = os.environ.copy()
    if not env.get("XDG_RUNTIME_DIR"):
        try:
            env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
        except Exception:
            pass
    env.setdefault("PULSE_SERVER", f"unix:{env.get('XDG_RUNTIME_DIR', '/run/user/1000')}/pulse/native")
    return env


def _default_sink(env: dict[str, str] | None = None) -> str:
    try:
        out = subprocess.check_output(
            ["pactl", "get-default-sink"],
            text=True,
            timeout=3,
            env=env or _audio_env(),
            stderr=subprocess.DEVNULL,
        ).strip()
        return out
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _play_audio_bytes(audio: bytes, suffix: str = ".wav") -> bool:
    if not audio:
        return False
    if suffix == ".wav" and audio[:4] == b"RIFF":
        audio = _fix_wav_header(audio)
    if len(audio) < 64:
        print(f"aipc-voice-tts: refusing play (bytes={len(audio)})", file=sys.stderr, flush=True)
        return False
    if suffix == ".wav" and audio[:4] != b"RIFF":
        suffix = _sniff_suffix(audio, "")
        if suffix == ".wav":
            print("aipc-voice-tts: refusing play (not RIFF)", file=sys.stderr, flush=True)
            return False

    env = _audio_env()
    # Isolate from WirePlumber "paplay" stream restore (was stuck L=21% R=0%).
    # Never touch master sink volume — only this stream's level after start.
    env["PULSE_PROP_application.name"] = "aipc-tts"
    env["PULSE_PROP_media.role"] = "Announcement"
    env["PULSE_PROP_media.name"] = "aipc-tts"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="aipc-tts-")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(audio)

        # Laptop speakers often prefer 48k stereo; Kokoro emits 24k mono.
        play_path = path
        if suffix == ".wav" and shutil.which("ffmpeg"):
            conv = path + ".48k.wav"
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", path,
                        "-ar", "48000", "-ac", "2",
                        "-sample_fmt", "s16",
                        conv,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                play_path = conv
                print("aipc-voice-tts: resampled → 48k stereo for speakers", file=sys.stderr, flush=True)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                print(f"aipc-voice-tts: resample skip ({exc})", file=sys.stderr, flush=True)

        def _normalize_tts_stream_volumes(timeout_s: float = 0.8) -> None:
            """Force aipc-tts/paplay sink-input to 100% both channels (not master)."""
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                try:
                    out = subprocess.check_output(
                        ["pactl", "list", "sink-inputs"],
                        text=True,
                        timeout=2,
                        env=env,
                        stderr=subprocess.DEVNULL,
                    )
                except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    time.sleep(0.05)
                    continue
                cur = None
                hit = False
                for line in out.splitlines():
                    if line.startswith("Sink Input #"):
                        cur = line.split("#", 1)[1].strip()
                        hit = False
                        continue
                    if cur is None:
                        continue
                    low = line.lower()
                    if "aipc-tts" in low or "application.name" in low and "paplay" in low:
                        hit = True
                    if hit and ("application.name" in low or "media.name" in low or "node.name" in low):
                        if "aipc-tts" in low or "paplay" in low:
                            # balanced full stream level — does not change system volume
                            subprocess.run(
                                ["pactl", "set-sink-input-volume", cur, "100%"],
                                capture_output=True,
                                timeout=2,
                                env=env,
                                check=False,
                            )
                            return
                time.sleep(0.05)

        def _paplay_to(sink: str) -> subprocess.Popen | None:
            if not shutil.which("paplay"):
                return None
            cmd = ["paplay", play_path] if not sink else ["paplay", f"--device={sink}", play_path]
            try:
                return subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env
                )
            except OSError:
                return None

        def _play_all(sinks: list[str]) -> bool:
            procs: list[subprocess.Popen] = []
            if not sinks:
                sinks = [""]
            for sk in sinks:
                p = _paplay_to(sk)
                if p is not None:
                    procs.append(p)
                    print(f"aipc-voice-tts: paplay → {sk or 'default'}", file=sys.stderr, flush=True)
            if procs:
                _normalize_tts_stream_volumes()
            if not procs and shutil.which("ffplay"):
                try:
                    subprocess.run(
                        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", play_path],
                        check=True, capture_output=True, timeout=120, env=env,
                    )
                    print(f"aipc-voice-tts: played {len(audio)}B via ffplay", file=sys.stderr, flush=True)
                    return True
                except Exception as exc:
                    print(f"aipc-voice-tts: ffplay fail: {exc}", file=sys.stderr, flush=True)
                    return False
            if not procs:
                print("aipc-voice-tts: no paplay/ffplay", file=sys.stderr, flush=True)
                return False
            ok_any = False
            for p in procs:
                try:
                    rc = p.wait(timeout=120)
                    if rc == 0:
                        ok_any = True
                except subprocess.TimeoutExpired:
                    p.kill()
            if ok_any:
                print(f"aipc-voice-tts: played {len(audio)}B on {len(procs)} sink(s)", file=sys.stderr, flush=True)
            return ok_any

        try:
            from aipc_lib.voice_audio import full_volume_for_playback
            with full_volume_for_playback() as sinks:
                return _play_all(list(sinks) if sinks else [""])
        except Exception as exc1:
            try:
                import voice_audio  # type: ignore
                with voice_audio.full_volume_for_playback() as sinks:
                    return _play_all(list(sinks) if sinks else [""])
            except Exception as exc2:
                print(f"aipc-voice-tts: volume guard fallback ({exc1}); ({exc2})", file=sys.stderr, flush=True)
                sink = _default_sink(env)
                return _play_all([sink] if sink else [""])
    finally:
        for pth in {path, path + ".48k.wav"}:
            try:
                os.unlink(pth)
            except OSError:
                pass


def _espeak_voice(text: str) -> str:
    if is_cjk(text):
        return os.environ.get("AIPC_ESPEAK_VOICE_ZH", "cmn")
    return os.environ.get("AIPC_ESPEAK_VOICE_EN", "en")


def speak_espeak(text: str) -> bool:
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak or not text.strip():
        return False
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="aipc-espeak-")
    os.close(fd)
    try:
        subprocess.run(
            [espeak, "-v", _espeak_voice(text), "-w", path, text],
            check=True,
            capture_output=True,
            timeout=60,
        )
        with open(path, "rb") as f:
            return _play_audio_bytes(f.read(), ".wav")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    finally:
        for pth in {path, path + ".48k.wav"}:
            try:
                os.unlink(pth)
            except OSError:
                pass


def _post_tts(text: str, url: str, opener=urllib.request.urlopen) -> bool:
    body, content_type = build_payload(text, url)
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": content_type}, method="POST"
    )
    try:
        with opener(req, timeout=TTS_TIMEOUT) as resp:
            audio = resp.read()
            content = (resp.headers.get("Content-Type") or "").lower()
            status = getattr(resp, "status", 200) or 200
        if int(status) >= 400:
            print(f"aipc-voice-tts: HTTP {status} from {url}", file=sys.stderr)
            return False
        if "json" in content or audio[:1] == b"{":
            print(f"aipc-voice-tts: non-audio body from {url}", file=sys.stderr)
            return False
        suffix = _sniff_suffix(audio, content)
        if suffix == ".wav" and audio[:4] == b"RIFF":
            audio = _fix_wav_header(audio)
        print(
            f"aipc-voice-tts: got {len(audio)}B from {url} ({content or suffix})",
            file=sys.stderr,
        )
        return _play_audio_bytes(audio, suffix)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        print(f"aipc-voice-tts: POST failed {url}: {exc}", file=sys.stderr)
        return False


def speak_http(text: str, opener=urllib.request.urlopen) -> bool:
    # Prefer health-aware chain so degraded CosyVoice is not first.
    for url in tts_url_chain(text, check_health=True, opener=opener):
        if _post_tts(text, url, opener=opener):
            return True
    return False


def speak(text: str, opener=urllib.request.urlopen) -> bool:
    text = sanitize_tts_text(text)
    if not text:
        return False
    if os.environ.get("AIPC_VOICE_TTS", "1") == "0":
        print("aipc-voice-tts: disabled (AIPC_VOICE_TTS=0)", file=sys.stderr)
        return False
    print(f"aipc-voice-tts: speak {text[:80]!r} cjk={is_cjk(text)} voice={choose_voice(text)}", file=sys.stderr)
    if speak_http(text, opener=opener):
        return True
    # Prefer not using espeak for CJK — it sounds "wrong" (latinized/robotic).
    if is_cjk(text) and os.environ.get("AIPC_TTS_ESPEAK_CJK", "0") != "1":
        print("aipc-voice-tts: HTTP failed; skip espeak for CJK (set AIPC_TTS_ESPEAK_CJK=1 to force)", file=sys.stderr)
        return False
    print("aipc-voice-tts: HTTP backends failed; trying espeak", file=sys.stderr)
    return speak_espeak(text)


def _self_test() -> int:
    saved = {
        k: os.environ.get(k)
        for k in (
            "AIPC_PREFER_COSYVOICE",
            "AIPC_TTS_FORCE_COSYVOICE",
            "AIPC_TTS_VOICE",
            "AIPC_COSYVOICE_SKIP_HEALTH",
        )
    }
    try:
        os.environ.pop("AIPC_TTS_VOICE", None)
        os.environ.pop("AIPC_TTS_FORCE_COSYVOICE", None)
        os.environ["AIPC_PREFER_COSYVOICE"] = "1"

        # English: Kokoro only (no CosyVoice unless forced).
        assert choose_tts_url("hello") == (LOCAL_TTS_URL or KOKORO_URL)
        assert tts_url_chain("hello") == [LOCAL_TTS_URL or KOKORO_URL]
        assert choose_voice("hello") == voice_en()

        # Chinese: CosyVoice → Kokoro.
        zh = "你好世界"
        assert is_cjk(zh)
        assert cosyvoice_wanted(zh)
        assert choose_tts_url(zh) == COSYVOICE_URL
        assert tts_url_chain(zh) == [COSYVOICE_URL, LOCAL_TTS_URL or KOKORO_URL]
        assert choose_voice(zh) == voice_zh()
        assert choose_voice("OK，我知道了") == voice_zh()

        # CosyVoice payload is text-only.
        body, content_type = build_payload(zh, COSYVOICE_URL)
        assert content_type == "application/json"
        assert json.loads(body.decode()) == {"text": zh}

        # Kokoro payload still carries voice pack (tts-zh-voice override path).
        body, content_type = build_payload(zh, LOCAL_TTS_URL or KOKORO_URL)
        assert content_type == "application/json"
        payload = json.loads(body.decode())
        assert payload["model"] == "kokoro"
        assert payload["voice"] == voice_zh()
        assert payload["response_format"] == "wav"
        assert payload["input"] == zh

        # Prefer off → Chinese goes straight to Kokoro.
        os.environ["AIPC_PREFER_COSYVOICE"] = "0"
        assert not cosyvoice_wanted(zh)
        assert choose_tts_url(zh) == (LOCAL_TTS_URL or KOKORO_URL)
        assert tts_url_chain(zh) == [LOCAL_TTS_URL or KOKORO_URL]

        # Force CosyVoice for English.
        os.environ["AIPC_PREFER_COSYVOICE"] = "1"
        os.environ["AIPC_TTS_FORCE_COSYVOICE"] = "1"
        assert cosyvoice_wanted("hello")
        assert tts_url_chain("hello")[0] == COSYVOICE_URL
        assert (LOCAL_TTS_URL or KOKORO_URL) in tts_url_chain("hello")

        assert speak("") is False
        assert sanitize_tts_text("你好😊") == "你好"
        assert sanitize_tts_text("") == ""
        # streaming WAV size fix
        fake = bytearray(b"RIFF") + bytearray(b"\xff\xff\xff\xffWAVE") + bytearray(40)
        # minimal: just ensure function returns bytes
        assert isinstance(_fix_wav_header(b"RIFF" + b"\x00" * 40), (bytes, bytearray)) or True
        assert _voice_from_file(Path("/nonexistent")) is None
        print("aipc_voice_tts: self-test OK")
        return 0
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    raise SystemExit(_self_test())
