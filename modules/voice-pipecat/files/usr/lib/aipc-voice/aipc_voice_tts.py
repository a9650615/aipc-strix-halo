"""TTS router: Kokoro-82M neural (zh+en) first, espeak only as last resort.

Chinese defaults to zf_xiaoyi (clearer assistant Mandarin). English: af_heart.
OpenAI-compatible endpoint: POST :8880/v1/audio/speech

Voice override order (first wins):
  AIPC_TTS_VOICE env → /etc/aipc/voice/tts-zh-voice or tts-en-voice → built-in default
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

COSYVOICE_URL = os.environ.get("AIPC_COSYVOICE_URL", "http://127.0.0.1:9880/tts")
KOKORO_URL = os.environ.get("AIPC_KOKORO_URL", "http://127.0.0.1:8880/v1/audio/speech")
LOCAL_TTS_URL = os.environ.get("AIPC_LOCAL_TTS_URL", KOKORO_URL)
TTS_TIMEOUT = float(os.environ.get("AIPC_TTS_TIMEOUT", "90"))

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


def choose_tts_url(text: str) -> str:
    # CosyVoice only when explicitly preferred and CJK (clone / higher fidelity).
    if is_cjk(text) and os.environ.get("AIPC_PREFER_COSYVOICE", "0") == "1":
        return COSYVOICE_URL
    return LOCAL_TTS_URL or KOKORO_URL


def build_payload(text: str, url: str) -> tuple[bytes, str]:
    if "audio/speech" in url or url in (KOKORO_URL, LOCAL_TTS_URL):
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
    return json.dumps({"text": text}).encode(), "application/json"


def _play_audio_bytes(audio: bytes, suffix: str = ".wav") -> bool:
    if not audio:
        return False
    players: list[list[str]] = []
    if suffix in (".wav", ".flac"):
        if shutil.which("paplay"):
            players.append(["paplay", "{path}"])
        if shutil.which("aplay"):
            players.append(["aplay", "-q", "{path}"])
    if shutil.which("ffplay"):
        players.append(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "{path}"])
    if shutil.which("mpv"):
        players.append(["mpv", "--no-video", "--really-quiet", "{path}"])
    if not players and shutil.which("paplay"):
        players.append(["paplay", "{path}"])
    if not players:
        return False

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="aipc-tts-")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(audio)
        for tmpl in players:
            cmd = [c.format(path=path) for c in tmpl]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                return True
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
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


def speak_http(text: str, opener=urllib.request.urlopen) -> bool:
    url = choose_tts_url(text)
    body, content_type = build_payload(text, url)
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": content_type}, method="POST"
    )
    try:
        with opener(req, timeout=TTS_TIMEOUT) as resp:
            audio = resp.read()
            content = (resp.headers.get("Content-Type") or "").lower()
        if "json" in content:
            return False
        if "mpeg" in content or "mp3" in content:
            suffix = ".mp3"
        elif "opus" in content:
            suffix = ".opus"
        elif "flac" in content:
            suffix = ".flac"
        else:
            suffix = ".wav"
        return _play_audio_bytes(audio, suffix)
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def speak(text: str, opener=urllib.request.urlopen) -> bool:
    if not text or not str(text).strip():
        return False
    if os.environ.get("AIPC_VOICE_TTS", "1") == "0":
        return False
    if speak_http(text, opener=opener):
        return True
    return speak_espeak(text)


def _self_test() -> int:
    assert choose_tts_url("hello") == LOCAL_TTS_URL
    assert choose_voice("hello") == voice_en()
    assert choose_voice("你好世界") == voice_zh()
    assert choose_voice("OK，我知道了") == voice_zh()  # mixed, still CJK-led
    body, content_type = build_payload("你好", LOCAL_TTS_URL)
    assert content_type == "application/json"
    payload = json.loads(body.decode())
    assert payload["model"] == "kokoro"
    assert payload["voice"] == voice_zh()
    assert payload["response_format"] == "wav"
    assert speak("") is False
    assert _voice_from_file(Path("/nonexistent")) is None
    print("aipc_voice_tts: self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
