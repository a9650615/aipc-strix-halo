#!/usr/bin/env python3
"""Always-on wake listener that triggers aipc-voice-once.

v0 strategy (hardware-first, boring-over-clever):
- Prefer openWakeWord when the package + model are present.
- Fall back to energy-based VAD push-to-listen so the always-on path
  still works without a trained custom model (firstboot train lands later).
- Honour /run/aipc/voice-mute (created when aipc-voice-mute.target is active).
"""

from __future__ import annotations

import argparse
import array
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

MUTE_FLAG = Path(os.environ.get("AIPC_VOICE_MUTE_FLAG", "/run/aipc/voice-mute"))
ONCE_CMD = os.environ.get("AIPC_VOICE_ONCE", "/usr/bin/aipc-voice-once")
RECORD_SECONDS = int(os.environ.get("AIPC_VOICE_RECORD_SECONDS", "5"))
SAMPLE_RATE = 16000
FRAME_MS = 30
ENERGY_THRESHOLD = float(os.environ.get("AIPC_WAKE_ENERGY", "1200"))
COOLDOWN_S = float(os.environ.get("AIPC_WAKE_COOLDOWN", "8"))
MODEL_PATH = Path(
    os.environ.get(
        "AIPC_WAKE_MODEL",
        "/var/lib/aipc-voice/wake/user-model.onnx",
    )
)
PRETRAINED = os.environ.get("AIPC_WAKE_PRETRAINED", "hey_jarvis")


def muted() -> bool:
    return MUTE_FLAG.exists()


def trigger_once() -> None:
    env = os.environ.copy()
    # Wake already listened; one-shot should still speak if TTS available.
    subprocess.Popen(
        [ONCE_CMD, "--seconds", str(RECORD_SECONDS)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _rms(frame: bytes) -> float:
    if len(frame) < 2:
        return 0.0
    n = len(frame) // 2
    samples = array.array("h")
    samples.frombytes(frame[: n * 2])
    if not samples:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / len(samples)) ** 0.5


def run_energy_loop() -> int:
    """Energy VAD: high RMS for ~200ms → trigger once (debounced)."""
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    print(
        f"aipc-voice-wake: energy mode threshold={ENERGY_THRESHOLD} "
        f"cooldown={COOLDOWN_S}s (openWakeWord not available or no model)",
        flush=True,
    )
    proc = subprocess.Popen(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-t",
            "raw",
            "-q",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    last = 0.0
    high = 0
    try:
        while True:
            if muted():
                time.sleep(0.2)
                # drain a bit so buffer doesn't grow forever
                proc.stdout.read(frame_bytes)
                continue
            data = proc.stdout.read(frame_bytes)
            if not data:
                time.sleep(0.05)
                continue
            if _rms(data) >= ENERGY_THRESHOLD:
                high += 1
            else:
                high = 0
            now = time.monotonic()
            if high >= 4 and (now - last) >= COOLDOWN_S:
                last = now
                high = 0
                print("aipc-voice-wake: energy trigger → aipc-voice-once", flush=True)
                trigger_once()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def run_openwakeword() -> int:
    try:
        import openwakeword  # type: ignore
        from openwakeword.model import Model  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-voice-wake: openwakeword import failed: {exc}", flush=True)
        return run_energy_loop()

    models: dict[str, str] = {}
    if MODEL_PATH.is_file():
        models[MODEL_PATH.stem] = str(MODEL_PATH)
        print(f"aipc-voice-wake: loading user model {MODEL_PATH}", flush=True)
        oww = Model(wakeword_models=list(models.values()), inference_framework="onnx")
    else:
        print(f"aipc-voice-wake: loading pretrained {PRETRAINED}", flush=True)
        try:
            openwakeword.utils.download_models()
        except Exception:
            pass
        oww = Model(wakeword_models=[PRETRAINED], inference_framework="onnx")

    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    proc = subprocess.Popen(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-t",
            "raw",
            "-q",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    last = 0.0
    threshold = float(os.environ.get("AIPC_WAKE_THRESHOLD", "0.5"))
    print(f"aipc-voice-wake: openWakeWord ready threshold={threshold}", flush=True)
    try:
        while True:
            if muted():
                time.sleep(0.2)
                proc.stdout.read(frame_bytes)
                continue
            data = proc.stdout.read(frame_bytes)
            if not data or len(data) < frame_bytes:
                continue
            # openWakeWord expects int16 numpy array; avoid hard numpy dep if possible
            try:
                import numpy as np  # type: ignore

                audio = np.frombuffer(data, dtype=np.int16)
            except Exception:
                audio = struct.unpack(f"<{len(data) // 2}h", data)
            prediction = oww.predict(audio)
            score = max(float(v) for v in prediction.values()) if prediction else 0.0
            now = time.monotonic()
            if score >= threshold and (now - last) >= COOLDOWN_S:
                last = now
                print(f"aipc-voice-wake: detected score={score:.2f} → once", flush=True)
                trigger_once()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def train_stub(samples_dir: Path, out_path: Path, label: str) -> int:
    """Documented training entrypoint; full openWakeWord training is heavy.

    For v0 we copy the best-effort note and write a persona marker so the
    loader path exists. Real ONNX fit lands with firstboot (task 2.1).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wavs = sorted(samples_dir.glob("*.wav"))
    if len(wavs) < 1:
        print("aipc-voice-train-wake: need at least 1 WAV in samples dir", file=sys.stderr)
        return 1
    marker = out_path.with_suffix(".txt")
    marker.write_text(
        f"label={label}\nsamples={len(wavs)}\n"
        "status=pending-onnx-fit\n"
        "note=v0 trains a marker; openWakeWord custom ONNX fit is firstboot follow-up\n"
    )
    print(f"aipc-voice-train-wake: wrote marker {marker} ({len(wavs)} samples for '{label}')")
    print("aipc-voice-train-wake: runtime will use pretrained/energy until ONNX fit ships")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--mode", choices=("auto", "energy", "openwakeword"), default="auto")
    p.add_argument("--train", action="store_true", help="run train stub")
    p.add_argument("--samples", type=Path, default=Path("/var/lib/aipc-voice/wake/samples"))
    p.add_argument("--label", default="assistant")
    p.add_argument("--out", type=Path, default=MODEL_PATH)
    return p


def _self_test() -> int:
    assert _rms(b"\x00\x00" * 100) == 0.0
    loud = struct.pack("<h", 10000) * 200
    assert _rms(loud) > 1000
    assert MUTE_FLAG.as_posix().startswith("/")
    print("aipc-voice-wake: self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.train:
        return train_stub(args.samples, args.out, args.label)
    mode = args.mode
    if mode == "energy":
        return run_energy_loop()
    if mode == "openwakeword":
        return run_openwakeword()
    # auto
    try:
        import openwakeword  # noqa: F401

        return run_openwakeword()
    except Exception:
        return run_energy_loop()


if __name__ == "__main__":
    raise SystemExit(main())
