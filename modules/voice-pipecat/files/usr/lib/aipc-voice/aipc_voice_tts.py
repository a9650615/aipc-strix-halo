from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

COSYVOICE_URL = os.environ.get("AIPC_COSYVOICE_URL", "http://127.0.0.1:9880/tts")
KOKORO_URL = os.environ.get("AIPC_KOKORO_URL", "http://127.0.0.1:8880/v1/audio/speech")
TTS_TIMEOUT = float(os.environ.get("AIPC_TTS_TIMEOUT", "8"))

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def choose_tts_url(text: str) -> str:
    return COSYVOICE_URL if _CJK_RE.search(text) else KOKORO_URL


def build_payload(text: str, url: str) -> tuple[bytes, str]:
    if url == KOKORO_URL:
        return json.dumps({"model": "kokoro", "voice": "af_heart", "input": text}).encode(), "application/json"
    return json.dumps({"text": text}).encode(), "application/json"


def speak(text: str, opener=urllib.request.urlopen) -> bool:
    url = choose_tts_url(text)
    body, content_type = build_payload(text, url)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
    try:
        with opener(req, timeout=TTS_TIMEOUT) as resp:
            resp.read()
        return True
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def _self_test() -> int:
    assert choose_tts_url("你好") == COSYVOICE_URL
    assert choose_tts_url("hello") == KOKORO_URL
    body, content_type = build_payload("hello", KOKORO_URL)
    assert content_type == "application/json"
    assert json.loads(body.decode())["input"] == "hello"
    print("aipc_voice_tts: self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
