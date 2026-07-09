"""Local TTS router: HTTP services first, espeak-ng fallback, always play audio."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

COSYVOICE_URL = os.environ.get("AIPC_COSYVOICE_URL", "http://127.0.0.1:9880/tts")
KOKORO_URL = os.environ.get("AIPC_KOKORO_URL", "http://127.0.0.1:8880/v1/audio/speech")
LOCAL_TTS_URL = os.environ.get("AIPC_LOCAL_TTS_URL", "http://127.0.0.1:8880/v1/audio/speech")
TTS_TIMEOUT = float(os.environ.get("AIPC_TTS_TIMEOUT", "20"))

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def choose_tts_url(text: str) -> str:
    """Prefer local OpenAI-speech compatible service; CosyVoice for CJK when set."""
    if _CJK_RE.search(text) and os.environ.get("AIPC_PREFER_COSYVOICE", "0") == "1":
        return COSYVOICE_URL
    return LOCAL_TTS_URL or KOKORO_URL


def build_payload(text: str, url: str) -> tuple[bytes, str]:
    if "audio/speech" in url or url == KOKORO_URL or url == LOCAL_TTS_URL:
        return (
            json.dumps(
                {
                    "model": os.environ.get("AIPC_TTS_MODEL", "local"),
                    "voice": os.environ.get("AIPC_TTS_VOICE", "default"),
                    "input": text,
                    "response_format": "wav",
                }
            ).encode(),
            "application/json",
        )
    return json.dumps({"text": text}).encode(), "application/json"


def _play_wav_bytes(audio: bytes) -> bool:
    if not audio:
        return False
    player = shutil.which("paplay") or shutil.which("aplay")
    if not player:
        return False
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="aipc-tts-")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(audio)
        # basename check: "paplay".endswith("aplay") is True — do not use endswith.
        base = os.path.basename(player)
        if base == "aplay":
            cmd = [player, "-q", path]
        else:
            cmd = [player, path]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _espeak_voice(text: str) -> str:
    if _CJK_RE.search(text):
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
            return _play_wav_bytes(f.read())
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
            # some services wrap base64; treat as failure and fall through
            return False
        return _play_wav_bytes(audio)
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def speak(text: str, opener=urllib.request.urlopen) -> bool:
    """Speak `text`. Prefer local HTTP TTS; fall back to espeak-ng."""
    if not text or not str(text).strip():
        return False
    if os.environ.get("AIPC_VOICE_TTS", "1") == "0":
        return False
    if speak_http(text, opener=opener):
        return True
    return speak_espeak(text)


def _self_test() -> int:
    assert choose_tts_url("hello") == LOCAL_TTS_URL
    body, content_type = build_payload("hello", LOCAL_TTS_URL)
    assert content_type == "application/json"
    assert json.loads(body.decode())["input"] == "hello"
    assert _espeak_voice("你好") == os.environ.get("AIPC_ESPEAK_VOICE_ZH", "cmn")
    assert _espeak_voice("hello") == os.environ.get("AIPC_ESPEAK_VOICE_EN", "en")
    assert speak("") is False
    print("aipc_voice_tts: self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
