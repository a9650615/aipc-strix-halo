"""CosyVoice3 zero-shot clone TTS HTTP service (stdlib only).

Contract:
  GET  /healthz → {"status":"ok|degraded","backend":"cosyvoice3","clone":bool}
  POST /tts     JSON {"text":"...","prompt_wav": optional path, "prompt_text": optional}
              → audio/wav  or JSON error

When the CosyVoice checkout / model / deps are missing the process stays up:
healthz reports degraded and /tts returns 503. No crash-loop on first boot
before the runtime model pull.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = os.environ.get("AIPC_COSYVOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("AIPC_COSYVOICE_PORT", "9880"))
MODEL_DIR = os.environ.get(
    "AIPC_COSYVOICE_MODEL",
    "/var/lib/aipc-voice/models/cosyvoice3/Fun-CosyVoice3-0.5B-2512",
)
CLONE_WAV = os.environ.get(
    "AIPC_CLONE_WAV",
    "/var/lib/aipc-voice/persona/clone.wav",
)
PROMPT_TEXT_DEFAULT = os.environ.get(
    "AIPC_CLONE_PROMPT_TEXT",
    "希望你以后能够做的比我还好呦。 <|endofprompt|>",
)
COSYVOICE_ROOT = os.environ.get(
    "AIPC_COSYVOICE_ROOT",
    "/var/lib/aipc-voice/cosyvoice",
)
CHECKOUT = os.environ.get(
    "AIPC_COSYVOICE_CHECKOUT",
    os.path.join(COSYVOICE_ROOT, "CosyVoice"),
)
MATCHA = os.path.join(CHECKOUT, "third_party", "Matcha-TTS")
DEVICE = os.environ.get("AIPC_COSYVOICE_DEVICE", "cpu")

_model = None
_model_lock = threading.Lock()
_model_error: str | None = None


def _clone_present() -> bool:
    return Path(CLONE_WAV).is_file()


def _model_present() -> bool:
    """Require real weight files, not a partial download."""
    p = Path(MODEL_DIR)
    if not p.is_dir():
        return False
    def present(name: str) -> bool:
        return (p / name).is_file() and (p / name).stat().st_size > 0

    # CosyVoice3 ships either llm.pt or llm.rl.pt depending on the variant.
    return all(
        [
            present("flow.pt"),
            present("hift.pt"),
            present("speech_tokenizer_v3.onnx"),
            present("campplus.onnx"),
            present("cosyvoice3.yaml"),
            present("configuration.json"),
            present("CosyVoice-BlankEN/model.safetensors"),
            present("llm.pt") or present("llm.rl.pt"),
        ]
    )


def _ensure_llm_alias() -> None:
    p = Path(MODEL_DIR)
    llm_pt = p / "llm.pt"
    llm_rl = p / "llm.rl.pt"
    if llm_pt.exists() or not llm_rl.is_file():
        return
    llm_pt.symlink_to("llm.rl.pt")


def _checkout_present() -> bool:
    return Path(CHECKOUT, "cosyvoice", "cli", "cosyvoice.py").is_file()


def _prepare_sys_path() -> None:
    for path in (CHECKOUT, MATCHA):
        if path and path not in sys.path and os.path.isdir(path):
            sys.path.insert(0, path)


def backend_ready() -> bool:
    return _checkout_present() and _model_present() and _model_error is None


def _load_model():
    """Lazy-load CosyVoice3. Returns the model or raises RuntimeError."""
    global _model, _model_error
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        if not _checkout_present():
            raise RuntimeError(
                f"CosyVoice checkout missing at {CHECKOUT}; "
                "install runtime under /var/lib/aipc-voice/cosyvoice/"
            )
        _ensure_llm_alias()
        if not _model_present():
            raise RuntimeError(
                f"CosyVoice3 model missing at {MODEL_DIR}; "
                "pull Fun-CosyVoice3-0.5B-2512 at runtime (not at image build)"
            )
        _prepare_sys_path()
        try:
            from cosyvoice.cli.cosyvoice import AutoModel  # type: ignore
        except Exception as exc:  # noqa: BLE001
            _model_error = f"import failed: {exc}"
            raise RuntimeError(
                f"CosyVoice import failed ({exc}). "
                "Run this service under the cosyvoice venv "
                f"({COSYVOICE_ROOT}/venv/bin/python3)."
            ) from exc
        try:
            # load_jit/load_trt off: no GPU assumptions; device via env for later.
            _model = AutoModel(
                model_dir=MODEL_DIR,
                load_jit=False,
                load_trt=False,
                fp16=False,
            )
            _model_error = None
            return _model
        except TypeError:
            # Older AutoModel signature without load_* kwargs.
            _model = AutoModel(model_dir=MODEL_DIR)
            _model_error = None
            return _model
        except Exception as exc:  # noqa: BLE001
            _model_error = str(exc)
            raise RuntimeError(f"CosyVoice3 load failed: {exc}") from exc


def synthesize_wav(
    text: str,
    prompt_wav: str | None = None,
    prompt_text: str | None = None,
) -> bytes:
    if not text or not str(text).strip():
        raise ValueError("empty text")
    wav_path = prompt_wav or CLONE_WAV
    if not Path(wav_path).is_file():
        raise FileNotFoundError(f"prompt_wav not found: {wav_path}")
    model = _load_model()
    ptext = prompt_text if prompt_text is not None else PROMPT_TEXT_DEFAULT
    if "<|endofprompt|>" not in ptext:
        ptext = f"{ptext.rstrip()} <|endofprompt|>"

    import torch  # type: ignore
    import torchaudio  # type: ignore

    chunks: list = []
    for item in model.inference_zero_shot(
        str(text),
        ptext,
        wav_path,
        stream=False,
    ):
        speech = item.get("tts_speech") if isinstance(item, dict) else item
        if speech is None:
            continue
        chunks.append(speech)
    if not chunks:
        raise RuntimeError("CosyVoice returned no audio")
    audio = torch.cat(chunks, dim=-1) if len(chunks) > 1 else chunks[0]
    sample_rate = getattr(model, "sample_rate", 24000)
    buf = io.BytesIO()
    # torchaudio expects (channels, samples)
    if audio.dim() == 1:
        audio = audio.unsqueeze(0)
    torchaudio.save(buf, audio.cpu(), sample_rate, format="wav")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "aipc-tts-cosyvoice/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

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
            ready = backend_ready()
            # Probe import path lightly without forcing full model load.
            status = "ok" if ready and _model is not None else (
                "ok" if ready else "degraded"
            )
            if ready and _model is None:
                # Model dir + checkout present but not yet loaded: still "ok"
                # once first /tts succeeds; report degraded until then only if
                # a previous load failed.
                status = "degraded" if _model_error else "ok"
            self._send_json(
                200,
                {
                    "status": status,
                    "backend": "cosyvoice3",
                    "clone": _clone_present(),
                    "model_dir": MODEL_DIR,
                    "model_present": _model_present(),
                    "checkout_present": _checkout_present(),
                    "device": DEVICE,
                    "error": _model_error,
                },
            )
            return
        self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/tts", "/v1/audio/speech"):
            self._send_json(404, {"detail": "not found"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"detail": "invalid json"})
            return
        text = payload.get("text") or payload.get("input") or ""
        prompt_wav = payload.get("prompt_wav") or None
        prompt_text = payload.get("prompt_text")
        if not backend_ready() and not _checkout_present():
            self._send_json(
                503,
                {
                    "detail": (
                        "CosyVoice not installed yet. Expected checkout at "
                        f"{CHECKOUT} and model at {MODEL_DIR}."
                    ),
                },
            )
            return
        if not _model_present():
            self._send_json(
                503,
                {
                    "detail": (
                        f"CosyVoice3 model not present at {MODEL_DIR}. "
                        "Pull weights at runtime (not during image build)."
                    ),
                },
            )
            return
        try:
            audio = synthesize_wav(
                str(text),
                prompt_wav=str(prompt_wav) if prompt_wav else None,
                prompt_text=str(prompt_text) if prompt_text is not None else None,
            )
        except FileNotFoundError as exc:
            self._send_json(400, {"detail": str(exc)})
            return
        except ValueError as exc:
            self._send_json(400, {"detail": str(exc)})
            return
        except RuntimeError as exc:
            self._send_json(503, {"detail": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send_json(500, {"detail": str(exc)})
            return
        self._send(200, audio, "audio/wav")


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"aipc-tts-cosyvoice listening on http://{HOST}:{PORT} "
        f"(clone={_clone_present()} model={_model_present()} "
        f"checkout={_checkout_present()})",
        flush=True,
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
