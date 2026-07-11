"""Audio front gate — short WAV → ignore | stt_then_route | route.

v1: heuristic RMS/duration (no STT text). Same JSON for a future audio model.
"""

from __future__ import annotations

import array
import io
import os
import struct
import time
import wave
from typing import Any

from fastapi import FastAPI, Request, Response

app = FastAPI(title="aipc-voice-audio-front")

SPEECH_RMS = float(os.environ.get("AIPC_AUDIO_FRONT_SPEECH_RMS", "3500"))
MIN_S = float(os.environ.get("AIPC_AUDIO_FRONT_MIN_S", "0.35"))
MIN_CONF = float(os.environ.get("AIPC_AUDIO_FRONT_MIN_CONF", "0.55"))


def _pcm_rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    n = len(pcm) // 2
    samples = array.array("h")
    samples.frombytes(pcm[: n * 2])
    if not samples:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / len(samples)) ** 0.5


def _wav_pcm(data: bytes) -> tuple[bytes, int]:
    """Return (pcm_s16le, sample_rate). Raw s16le@16k if not RIFF."""
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as w:
            rate = w.getframerate()
            nch = w.getnchannels()
            sw = w.getsampwidth()
            frames = w.readframes(w.getnframes())
        if sw != 2:
            return b"", rate
        if nch > 1:
            # downmix: take left
            out = bytearray()
            step = nch * 2
            for i in range(0, len(frames) - step + 1, step):
                out.extend(frames[i : i + 2])
            frames = bytes(out)
        return frames, rate
    return data, 16000


def gate_pcm(pcm: bytes, sample_rate: int = 16000) -> dict[str, Any]:
    t0 = time.monotonic()
    dur = len(pcm) / 2 / max(1, sample_rate)
    rms = _pcm_rms(pcm)
    # Cheap noise estimate: first 100ms vs whole
    head_n = min(len(pcm), int(sample_rate * 0.1) * 2)
    head_rms = _pcm_rms(pcm[:head_n]) if head_n >= 2 else 0.0
    # Strong speech: clearly above thr, or above thr with mild head boost.
    # Soft band (0.7×–1.0× thr): still stt_then_route — mid-volume Chinese
    # speech (hardware rms~3856 vs thr 3500) was false-ignored at conf=0.45.
    strong = dur >= MIN_S and (
        rms >= SPEECH_RMS * 1.25
        or (rms >= SPEECH_RMS and rms >= head_rms * 1.08)
    )
    soft = dur >= MIN_S and rms >= SPEECH_RMS * 0.7
    speech_like = strong or soft
    conf = 0.0
    if strong:
        conf = min(1.0, 0.4 + (rms - SPEECH_RMS) / max(SPEECH_RMS, 1.0) * 0.3)
        conf = max(MIN_CONF, conf)
        action = "stt_then_route"
    elif soft:
        conf = round(min(MIN_CONF, 0.4 + (rms / max(SPEECH_RMS, 1.0)) * 0.2), 3)
        action = "stt_then_route"
    else:
        conf = (
            min(1.0, 0.5 + (SPEECH_RMS - rms) / max(SPEECH_RMS, 1.0) * 0.4)
            if rms < SPEECH_RMS
            else 0.45
        )
        action = "ignore"
    ms = (time.monotonic() - t0) * 1000
    return {
        "has_speech": bool(speech_like),
        "action": action,
        "target": None,
        "mode": None,
        "confidence": round(conf, 3),
        "latency_ms": round(ms, 2),
        "source": "heuristic",
        "rms": round(rms, 1),
        "duration_s": round(dur, 3),
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "voice-audio-front", "backend": "heuristic"}


@app.post("/gate")
async def gate(request: Request) -> dict:
    data = await request.body()
    if not data:
        return {
            "has_speech": False,
            "action": "ignore",
            "target": None,
            "mode": None,
            "confidence": 1.0,
            "latency_ms": 0.0,
            "source": "heuristic",
            "notes": "empty body",
        }
    pcm, rate = _wav_pcm(data)
    if not pcm:
        return {
            "has_speech": False,
            "action": "stt_then_route",
            "target": None,
            "mode": None,
            "confidence": 0.0,
            "latency_ms": 0.0,
            "source": "heuristic",
            "notes": "unparsed wav → fail-soft STT",
        }
    return gate_pcm(pcm, rate)


def self_test() -> None:
    # silence
    sil = struct.pack(f"<{16000}h", *([0] * 16000))
    r = gate_pcm(sil, 16000)
    assert r["action"] == "ignore", r
    # loud synthetic tone-ish (high amplitude noise)
    import random

    random.seed(0)
    loud = array.array("h", [int(random.gauss(0, 8000)) for _ in range(16000)])
    r2 = gate_pcm(loud.tobytes(), 16000)
    assert r2["has_speech"] or r2["action"] == "stt_then_route", r2
    print("voice-audio-front self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
