"""CosyVoice3 zero-shot clone TTS HTTP service (stdlib only).

Contract:
  GET  /healthz → {"status":"ok|degraded","backend":"cosyvoice3","clone":bool}
  POST /tts     JSON {
                    "text":"...",
                    "prompt_wav": optional path,
                    "prompt_text": optional transcript of prompt wav,
                    "mode": optional "zero_shot"|"instruct2" (default env),
                    "instruct": optional instruct2 system text
                 }
              → audio/wav  or JSON error

CosyVoice3 prompt_text format (zero_shot):
  "You are a helpful assistant. <style>. <|endofprompt|> <audio transcript>"
Not "transcript <|endofprompt|>" alone — that drifts to mainland Putonghua prior.

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
# Transcript-only fallback (no system prefix). Prefer clone.txt next to wav.
PROMPT_TEXT_DEFAULT = os.environ.get(
    "AIPC_CLONE_PROMPT_TEXT",
    "唉，你真好，好帥哦。",
)
# CosyVoice3 system side of prompt_text (before <|endofprompt|>).
# Active voice template may override via /var/lib/aipc-voice/persona/active.json.
# Default: young TW girl vibe (avoid mature「阿姨感」) + less retroflex.
_DEFAULT_SYSTEM = (
    "You are a helpful assistant. "
    "请用台湾国语、年轻少女声线（大约二十岁）表达：清亮偏高、轻快可爱、"
    "像同龄女生聊天，不要成熟御姐，绝对不要阿姨感或大妈感；"
    "尽量不要捲舌音（少用或弱化 zh/ch/sh/r），不要大陆普通话腔调。"
)
SYSTEM_PROMPT = os.environ.get("AIPC_COSYVOICE_SYSTEM", _DEFAULT_SYSTEM)
# zero_shot (default) | instruct2
INFER_MODE = os.environ.get("AIPC_COSYVOICE_MODE", "zero_shot").strip().lower()
# instruct2-only text (must end with <|endofprompt|> after normalize)
INSTRUCT_DEFAULT = os.environ.get(
    "AIPC_COSYVOICE_INSTRUCT",
    (
        "You are a helpful assistant. "
        "请用台湾国语、年轻少女、清亮偏高、轻快可爱的语气说，"
        "不要阿姨感，少捲舌音，不要大陆普通话腔调。<|endofprompt|>"
    ),
)
ACTIVE_JSON = Path(
    os.environ.get(
        "AIPC_VOICE_ACTIVE_JSON",
        "/var/lib/aipc-voice/persona/active.json",
    )
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
# GPU inference is not thread-safe on ROCm (concurrent /tts OOMs / hangs).
# Serialize synth; reject extras when the wait queue is full (503 busy).
MAX_INFLIGHT = max(1, int(os.environ.get("AIPC_COSYVOICE_MAX_INFLIGHT", "2")))
QUEUE_WAIT_S = float(os.environ.get("AIPC_COSYVOICE_QUEUE_WAIT_S", "180"))
MAX_CHARS = max(1, int(os.environ.get("AIPC_COSYVOICE_MAX_CHARS", "800")))
# CosyVoice speed>1 shortens mel → faster speech (also lower wall-clock).
DEFAULT_SPEED = float(os.environ.get("AIPC_COSYVOICE_SPEED", "1.15"))
PRELOAD = os.environ.get("AIPC_COSYVOICE_PRELOAD", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _patch_torchaudio_soundfile() -> None:
    """ROCm torchaudio may require torchcodec; fall back to soundfile I/O."""
    try:
        import torch
        import torchaudio
        import soundfile as sf
        import numpy as np

        def _load(path, *args, **kwargs):
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return torch.from_numpy(data.T.copy()), int(sr)

        def _save(path, src, sample_rate, **kwargs):
            if hasattr(src, "detach"):
                arr = src.detach().cpu().numpy()
            else:
                arr = np.asarray(src)
            if arr.ndim == 2 and arr.shape[0] <= 8 and arr.shape[0] < arr.shape[1]:
                arr = arr.T
            # BytesIO has no extension — force WAV subtype.
            fmt = kwargs.get("format") or "WAV"
            if hasattr(path, "write"):
                sf.write(path, arr, int(sample_rate), format=str(fmt).upper())
            else:
                sf.write(str(path), arr, int(sample_rate), format=str(fmt).upper())

        torchaudio.load = _load  # type: ignore[assignment]
        torchaudio.save = _save  # type: ignore[assignment]
    except Exception:
        pass



_model = None
_model_lock = threading.Lock()
_model_error: str | None = None
# Serializes ROCm/CUDA synth. Separate from _model_lock (load only).
_gpu_lock = threading.Lock()
_queue_lock = threading.Lock()
_inflight = 0  # waiting for GPU + holding GPU
_busy_rejects = 0


class BusyError(RuntimeError):
    """Queue full or wait timed out — map to HTTP 503."""


def _queue_snapshot() -> dict:
    with _queue_lock:
        return {
            "inflight": _inflight,
            "max_inflight": MAX_INFLIGHT,
            "queue_wait_s": QUEUE_WAIT_S,
            "busy_rejects": _busy_rejects,
            "gpu_busy": _gpu_lock.locked(),
        }


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
            _patch_torchaudio_soundfile()
            # CosyVoice3 accepts load_trt/fp16; CosyVoice2 may also take load_jit.
            # Prefer fp16 on CUDA when available (faster on gfx1151 ROCm).
            use_fp16 = (
                os.environ.get("AIPC_COSYVOICE_FP16", "").strip() == "1"
                or (
                    os.environ.get("AIPC_COSYVOICE_FP16", "").strip() == ""
                    and DEVICE != "cpu"
                )
            )
            try:
                import torch  # type: ignore
                if not torch.cuda.is_available():
                    use_fp16 = False
            except Exception:
                use_fp16 = False
            try:
                _model = AutoModel(
                    model_dir=MODEL_DIR,
                    load_trt=False,
                    fp16=use_fp16,
                )
            except TypeError:
                try:
                    _model = AutoModel(
                        model_dir=MODEL_DIR,
                        load_jit=False,
                        load_trt=False,
                        fp16=use_fp16,
                    )
                except TypeError:
                    _model = AutoModel(model_dir=MODEL_DIR)
            _model_error = None
            return _model
        except Exception as exc:  # noqa: BLE001
            _model_error = str(exc)
            raise RuntimeError(f"CosyVoice3 load failed: {exc}") from exc


def _load_active_template() -> dict:
    """Optional overrides written by `aipc-voice-template apply`."""
    try:
        if ACTIVE_JSON.is_file():
            return json.loads(ACTIVE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _resolve_transcript(wav_path: str, prompt_text: str | None) -> str:
    if prompt_text is not None and str(prompt_text).strip():
        return str(prompt_text).strip()
    sibling = Path(wav_path).with_suffix(".txt")
    if sibling.is_file():
        return sibling.read_text(encoding="utf-8").strip()
    return (PROMPT_TEXT_DEFAULT or "").strip()


def _strip_endofprompt(text: str) -> str:
    return text.replace("<|endofprompt|>", "").strip()


def format_zero_shot_prompt(
    transcript: str,
    system: str | None = None,
) -> str:
    """CosyVoice3: system <|endofprompt|> audio-transcript."""
    body = _strip_endofprompt(transcript)
    # If caller already passed a full CosyVoice3 prompt, keep it.
    if "<|endofprompt|>" in (transcript or ""):
        return transcript.strip()
    sys_txt = _strip_endofprompt(system if system is not None else SYSTEM_PROMPT)
    if not sys_txt:
        sys_txt = "You are a helpful assistant."
    if not body:
        body = _strip_endofprompt(PROMPT_TEXT_DEFAULT) or "你好。"
    return f"{sys_txt}<|endofprompt|>{body}"


def format_instruct2_prompt(instruct: str | None = None) -> str:
    raw = (instruct if instruct is not None else INSTRUCT_DEFAULT) or ""
    raw = raw.strip()
    if not raw:
        raw = (
            "You are a helpful assistant. "
            "请用台湾国语口音表达，语调自然轻快，不要使用大陆普通话腔调。"
        )
    if "<|endofprompt|>" not in raw:
        raw = f"{raw.rstrip()} <|endofprompt|>"
    return raw


def _resolve_speed(speed: float | None, active: dict) -> float:
    if speed is not None:
        try:
            s = float(speed)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid speed: {speed!r}") from exc
    else:
        raw = active.get("speed")
        if raw is not None and str(raw).strip() != "":
            try:
                s = float(raw)
            except (TypeError, ValueError):
                s = DEFAULT_SPEED
        else:
            s = DEFAULT_SPEED
    if s < 0.5 or s > 2.0:
        raise ValueError(f"speed out of range 0.5–2.0: {s}")
    return s


def _synthesize_unlocked(
    text: str,
    prompt_wav: str | None = None,
    prompt_text: str | None = None,
    mode: str | None = None,
    instruct: str | None = None,
    system: str | None = None,
    speed: float | None = None,
) -> bytes:
    """Run Cosy inference. Caller must hold _gpu_lock."""
    wav_path = prompt_wav or CLONE_WAV
    if not Path(wav_path).is_file():
        raise FileNotFoundError(f"prompt_wav not found: {wav_path}")
    model = _load_model()
    active = _load_active_template()
    use_mode = (
        mode
        or active.get("mode")
        or INFER_MODE
        or "zero_shot"
    )
    use_mode = str(use_mode).strip().lower()
    if use_mode not in ("zero_shot", "instruct2"):
        raise ValueError(f"unsupported mode: {use_mode}")
    # Empty active system/instruct → fall back to env defaults (TW flat).
    use_system = system if system is not None else active.get("system")
    if use_system is not None and not str(use_system).strip():
        use_system = None
    if use_system is None:
        use_system = SYSTEM_PROMPT
    use_instruct = instruct if instruct is not None else active.get("instruct")
    if use_instruct is not None and not str(use_instruct).strip():
        use_instruct = None
    use_speed = _resolve_speed(speed, active)

    import torch  # type: ignore
    import torchaudio  # type: ignore

    chunks: list = []
    if use_mode == "instruct2":
        itext = format_instruct2_prompt(
            str(use_instruct) if use_instruct else None
        )
        for item in model.inference_instruct2(
            str(text),
            itext,
            wav_path,
            stream=False,
            speed=use_speed,
        ):
            speech = item.get("tts_speech") if isinstance(item, dict) else item
            if speech is None:
                continue
            chunks.append(speech)
    else:
        transcript = _resolve_transcript(wav_path, prompt_text)
        ptext = format_zero_shot_prompt(
            transcript,
            system=str(use_system) if use_system is not None else None,
        )
        for item in model.inference_zero_shot(
            str(text),
            ptext,
            wav_path,
            stream=False,
            speed=use_speed,
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
    if audio.dim() == 1:
        audio = audio.unsqueeze(0)
    torchaudio.save(buf, audio.cpu(), sample_rate, format="wav")
    return buf.getvalue()


def synthesize_wav(
    text: str,
    prompt_wav: str | None = None,
    prompt_text: str | None = None,
    mode: str | None = None,
    instruct: str | None = None,
    system: str | None = None,
    speed: float | None = None,
) -> bytes:
    global _inflight, _busy_rejects
    if not text or not str(text).strip():
        raise ValueError("empty text")
    t = str(text).strip()
    if len(t) > MAX_CHARS:
        raise ValueError(f"text too long ({len(t)} > {MAX_CHARS} chars)")

    with _queue_lock:
        if _inflight >= MAX_INFLIGHT:
            _busy_rejects += 1
            raise BusyError(
                f"cosyvoice busy (queue full inflight={_inflight}/{MAX_INFLIGHT})"
            )
        _inflight += 1
        depth = _inflight
    print(
        f"aipc-tts-cosyvoice: queue enter inflight={depth}/{MAX_INFLIGHT}",
        flush=True,
    )
    try:
        if not _gpu_lock.acquire(timeout=max(0.1, QUEUE_WAIT_S)):
            with _queue_lock:
                _busy_rejects += 1
            raise BusyError(
                f"cosyvoice busy (queue wait >{QUEUE_WAIT_S:.0f}s)"
            )
        try:
            return _synthesize_unlocked(
                t,
                prompt_wav=prompt_wav,
                prompt_text=prompt_text,
                mode=mode,
                instruct=instruct,
                system=system,
                speed=speed,
            )
        finally:
            _gpu_lock.release()
    finally:
        with _queue_lock:
            _inflight = max(0, _inflight - 1)
            left = _inflight
        print(
            f"aipc-tts-cosyvoice: queue leave inflight={left}/{MAX_INFLIGHT}",
            flush=True,
        )


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
            q = _queue_snapshot()
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
                    "mode": (_load_active_template().get("mode") or INFER_MODE),
                    "template": _load_active_template().get("template"),
                    "speed": DEFAULT_SPEED,
                    "error": _model_error,
                    "queue": q,
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
        mode = payload.get("mode")
        instruct = payload.get("instruct")
        system = payload.get("system")
        speed = payload.get("speed")
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
                mode=str(mode) if mode is not None else None,
                instruct=str(instruct) if instruct is not None else None,
                system=str(system) if system is not None else None,
                speed=float(speed) if speed is not None and str(speed) != "" else None,
            )
        except BusyError as exc:
            self._send_json(
                503,
                {"detail": str(exc), "retryable": True, "queue": _queue_snapshot()},
            )
            return
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
        f"checkout={_checkout_present()} speed={DEFAULT_SPEED} "
        f"preload={PRELOAD})",
        flush=True,
    )
    if PRELOAD and _checkout_present() and _model_present():
        try:
            print("aipc-tts-cosyvoice: preloading model…", flush=True)
            _load_model()
            print("aipc-tts-cosyvoice: model ready", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-tts-cosyvoice: preload failed (lazy later): {exc}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
