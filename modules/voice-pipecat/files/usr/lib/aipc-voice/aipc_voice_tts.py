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
    # Reject tiny / non-audio bodies (e.g. JSON error mislabeled as wav).
    if len(audio) < 64 or (suffix == ".wav" and audio[:4] != b"RIFF"):
        print(
            f"aipc-voice-tts: refusing play (bytes={len(audio)} suffix={suffix})",
            file=sys.stderr,
        )
        return False

    env = _audio_env()
    sink = _default_sink(env)
    players: list[list[str]] = []
    if suffix in (".wav", ".flac"):
        if shutil.which("paplay"):
            # Explicit sink so Bluetooth/default is obvious in logs.
            if sink:
                players.append(["paplay", f"--device={sink}", "{path}"])
            players.append(["paplay", "{path}"])
        if shutil.which("pw-play"):
            players.append(["pw-play", "{path}"])
        if shutil.which("aplay"):
            players.append(["aplay", "-q", "{path}"])
    if shutil.which("ffplay"):
        players.append(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "{path}"])
    if shutil.which("mpv"):
        players.append(["mpv", "--no-video", "--really-quiet", "{path}"])
    if not players:
        print("aipc-voice-tts: no player (paplay/aplay/ffplay/mpv)", file=sys.stderr)
        return False

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="aipc-tts-")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(audio)
        last_err = ""
        for tmpl in players:
            cmd = [c.format(path=path) for c in tmpl]
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    timeout=120,
                    env=env,
                )
                print(
                    f"aipc-voice-tts: played {len(audio)}B via {cmd[0]}"
                    + (f" sink={sink}" if sink else ""),
                    file=sys.stderr,
                )
                return True
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                last_err = str(exc)
                continue
        print(f"aipc-voice-tts: all players failed ({last_err})", file=sys.stderr)
        return False
    finally:
        try:
            os.unlink(path)
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
        try:
            os.unlink(path)
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
        if "mpeg" in content or "mp3" in content:
            suffix = ".mp3"
        elif "opus" in content:
            suffix = ".opus"
        elif "flac" in content:
            suffix = ".flac"
        else:
            suffix = ".wav"
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
    if not text or not str(text).strip():
        return False
    if os.environ.get("AIPC_VOICE_TTS", "1") == "0":
        print("aipc-voice-tts: disabled (AIPC_VOICE_TTS=0)", file=sys.stderr)
        return False
    if speak_http(text, opener=opener):
        return True
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
