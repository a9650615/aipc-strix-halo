"""Static tests for the `aipc voice timings` reader (no hardware).

openspec: voice-latency-instrumentation (capability voice-telemetry).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from aipc_lib import voice_timing  # noqa: E402


def _write(log: Path, rows: list[dict]) -> None:
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_missing_log_is_empty(tmp_path) -> None:
    assert voice_timing.read_records(path=str(tmp_path / "none.jsonl")) == []
    assert "no data" in voice_timing.format_report([])


def test_tail_selection(tmp_path) -> None:
    log = tmp_path / "turns.jsonl"
    _write(log, [{"path": "batch", "perceived_ms": float(i)} for i in range(10)])
    recs = voice_timing.read_records(path=str(log), last=3)
    assert [r["perceived_ms"] for r in recs] == [7.0, 8.0, 9.0]


def test_malformed_lines_skipped(tmp_path) -> None:
    log = tmp_path / "turns.jsonl"
    log.write_text(
        '{"path":"batch","perceived_ms":100}\n'
        "not json at all\n"
        "\n"
        '{"path":"stream","perceived_ms":50}\n',
        encoding="utf-8",
    )
    recs = voice_timing.read_records(path=str(log))
    assert len(recs) == 2
    assert voice_timing.means(recs)["perceived_ms"] == 75.0


def test_means_ignore_null_and_bool(tmp_path) -> None:
    recs = [
        {"perceived_ms": 100, "llm_ttft_ms": None, "tts_ttfa_ms": 20},
        {"perceived_ms": 200, "llm_ttft_ms": 40, "tts_ttfa_ms": True},
    ]
    m = voice_timing.means(recs)
    assert m["perceived_ms"] == 150.0
    assert m["llm_ttft_ms"] == 40.0  # single non-null sample
    assert m["tts_ttfa_ms"] == 20.0  # True is not counted as a number


def test_report_renders_without_crash(tmp_path) -> None:
    recs = [{"path": "batch", "perceived_ms": 1234.5, "tts_backend": "kokoro", "preset": "voice"}]
    text = voice_timing.format_report(recs)
    assert "perceived" in text and "kokoro" in text
    blob = voice_timing.format_report(recs, as_json=True)
    assert json.loads(blob)["count"] == 1
