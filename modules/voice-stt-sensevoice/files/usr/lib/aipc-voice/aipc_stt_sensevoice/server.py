"""FastAPI STT entrypoint for voice-stt-sensevoice.

openspec/changes/phase-3-voice tasks 1.3/3.1 — SenseVoice-Small, short
utterances (<10s). voice-pipecat will POST raw audio bytes here once wired
up; this is the reference contract, not that integration.
"""

import os
import tempfile

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from funasr import AutoModel

try:
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
except ImportError:  # pragma: no cover - depends on funasr internals
    def rich_transcription_postprocess(text: str) -> str:
        return text

app = FastAPI(title="aipc-voice-stt-sensevoice")

MODEL_ID = "iic/SenseVoiceSmall"
# ponytail: single global model, loaded once at import time (matches
# agent-orchestrator's _graph = supervisor() pattern) — fine for a
# single-tenant STT daemon, revisit if concurrent requests ever need
# per-request model state.
#
# Default is "cpu", NOT the iGPU, despite this module targeting ROCm/gfx1151
# hardware: hardware-verified 2026-07-06 that device="cuda:0" (ROCm reports
# itself to torch as the CUDA backend) SEGFAULTs inside libamdhip64.so while
# loading this exact model (torch==2.9.1+rocm6.4, funasr==1.3.14, real crash,
# not fabricated — confirmed via coredumpctl, `sig=11` in the HIP runtime,
# not our Python code). A segfault kills the whole process, so a Python
# try/except around AutoModel() cannot fall back gracefully — that pattern
# only handles catchable exceptions, so GPU is opt-in via AIPC_STT_DEVICE,
# not attempted by default. Known ceiling: CPU-only for now (confirmed fast
# enough — rtf_avg 0.092 real transcription on this host); revisit cuda:0
# once a torch/ROCm release fixes this crash for gfx1151.
_device = os.environ.get("AIPC_STT_DEVICE", "cpu")
_model = AutoModel(model=MODEL_ID, trust_remote_code=True, device=_device)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "model": MODEL_ID, "device": _device}


@app.post("/transcribe")
async def transcribe(request: Request):
    audio = await request.body()
    if not audio:
        return JSONResponse(status_code=400, content={"error": {"code": "empty_body", "message": "no audio bytes"}})
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        tmp.write(audio)
        tmp.flush()
        try:
            result = _model.generate(input=tmp.name, language="auto", use_itn=True)
        except Exception as exc:
            return JSONResponse(status_code=502, content={"error": {"code": "inference_error", "message": str(exc)}})
    raw_text = result[0]["text"] if result else ""
    return {"text": rich_transcription_postprocess(raw_text), "raw_text": raw_text, "device": _device}
