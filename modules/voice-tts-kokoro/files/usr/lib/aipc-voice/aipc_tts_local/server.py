"""Minimal local TTS HTTP service (stdlib only — no FastAPI/pydantic).

OpenAI-compatible speech endpoint shape used by aipc_voice_tts.py:

  POST /v1/audio/speech  JSON {"input": "...", "voice": "default", ...}
  → audio/wav
  GET  /healthz

Backend: espeak-ng (image package). Works on Python 3.14 without wheels.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")
VOICE_EN = os.environ.get("AIPC_ESPEAK_VOICE_EN", "en")
VOICE_ZH = os.environ.get("AIPC_ESPEAK_VOICE_ZH", "cmn")
ESPEAK = shutil.which("espeak-ng") or shutil.which("espeak")
HOST = os.environ.get("AIPC_TTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("AIPC_TTS_PORT", "8880"))


def _voice_for(text: str, voice: str) -> str:
    if voice and voice not in ("default", "af_heart", "local", "kokoro"):
        return voice
    return VOICE_ZH if _CJK_RE.search(text) else VOICE_EN


def synthesize_wav(text: str, voice: str = "default") -> bytes:
    if not ESPEAK:
        raise RuntimeError("espeak-ng not installed")
    if not text.strip():
        raise ValueError("empty input")
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="aipc-tts-svc-")
    os.close(fd)
    try:
        subprocess.run(
            [ESPEAK, "-v", _voice_for(text, voice), "-w", path, text],
            check=True,
            capture_output=True,
            timeout=60,
        )
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "aipc-tts-local/1.0"

    def log_message(self, fmt: str, *args) -> None:  # quieter journal
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/healthz", "/health", "/"):
            self._send_json(
                200,
                {
                    "status": "ok" if ESPEAK else "degraded",
                    "backend": "espeak-ng",
                    "espeak": ESPEAK or "",
                },
            )
            return
        self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/v1/audio/speech", "/tts"):
            self._send_json(404, {"detail": "not found"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"detail": "invalid json"})
            return
        text = payload.get("input") or payload.get("text") or ""
        voice = payload.get("voice") or "default"
        if not ESPEAK:
            self._send_json(503, {"detail": "espeak-ng missing"})
            return
        try:
            audio = synthesize_wav(str(text), str(voice))
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"detail": str(exc)})
            return
        self._send(200, audio, "audio/wav")


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"aipc-tts-local listening on http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()


# Uvicorn-style module path compatibility: `python -m aipc_tts_local.server`
if __name__ == "__main__":
    main()
