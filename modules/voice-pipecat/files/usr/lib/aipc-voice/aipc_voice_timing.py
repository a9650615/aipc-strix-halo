"""Minimal per-turn latency recorder (openspec: voice-latency-instrumentation).

Best-effort, stdlib-only. Records the three headline durations of a voice turn
and appends one JSON line to a size-capped log. It NEVER raises into the turn
path, and it NEVER stores transcript or reply text — only durations and a small
set of categorical labels.

Consumed by aipc-voice-once (batch baseline) and the voice-streaming-turn
worker; the streaming path fills llm_ttft, the batch path leaves it null. The
analytics reader (`aipc voice timings`) lives in tools/aipc_lib; percentile /
per-scenario reporting is a separate, deferred change.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

# headline duration -> (start mark, end mark)
_HEADLINE = {
    "perceived": ("capture_end", "play_start"),
    "llm_ttft": ("llm_request", "llm_first_token"),
    "tts_ttfa": ("tts_request", "tts_first_audio"),
}
# the only labels ever serialized — anything else a caller passes is dropped,
# so utterance text can never leak into the record.
_LABELS = ("path", "tts_backend", "preset")

DEFAULT_CAP = 5000


def enabled() -> bool:
    return os.environ.get("AIPC_VOICE_TIMING", "1").strip().lower() not in (
        "0",
        "off",
        "false",
        "no",
    )


def log_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "aipc-voice" / "turns.jsonl"


def _cap(cap: int | None) -> int:
    if cap is not None:
        return max(1, int(cap))
    try:
        return max(1, int(os.environ.get("AIPC_VOICE_TIMING_MAX", str(DEFAULT_CAP))))
    except ValueError:
        return DEFAULT_CAP


def _append_capped(p: Path, line: str, cap: int) -> None:
    """Append one line, retaining only the most recent `cap` lines.

    Rewrites the whole file each turn — fine for a small capped log, and it
    keeps the size bound trivially correct without a separate rotation step.
    """
    lines: list[str] = []
    if p.exists():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    lines.append(line)
    if len(lines) > cap:
        lines = lines[-cap:]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TurnTimer:
    """Collect monotonic stage marks for one turn; flush one record at the end."""

    def __init__(self, path: str = "batch") -> None:
        self._marks: dict[str, int] = {}
        self._labels: dict[str, str] = {"path": path}
        self._flags: dict[str, bool] = {}

    def mark(self, stage: str, ns: int | None = None) -> "TurnTimer":
        self._marks[stage] = time.monotonic_ns() if ns is None else int(ns)
        return self

    def context(self, **labels: object) -> "TurnTimer":
        for key, value in labels.items():
            if key in _LABELS and value is not None:
                self._labels[key] = str(value)
        return self

    def flag(self, name: str, value: bool = True) -> "TurnTimer":
        self._flags[str(name)] = bool(value)
        return self

    def _dur_ms(self, start: str, end: str) -> float | None:
        a, b = self._marks.get(start), self._marks.get(end)
        if a is None or b is None:
            return None
        return round((b - a) / 1e6, 1)

    def record(self, ts: float | None) -> dict:
        rec: dict = {"ts": ts, "path": self._labels.get("path", "batch")}
        for name, (start, end) in _HEADLINE.items():
            rec[f"{name}_ms"] = self._dur_ms(start, end)
        for key in _LABELS:
            if key != "path":
                rec[key] = self._labels.get(key)
        if self._flags:
            rec["flags"] = dict(self._flags)
        return rec

    def flush(self, path: str | None = None, cap: int | None = None) -> dict | None:
        """Best-effort write of one record. Returns the record, or None if
        disabled or on any error — never raises into the caller's turn."""
        if not enabled():
            return None
        try:
            rec = self.record(ts=time.time())
            target = Path(path) if path else log_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            _append_capped(target, json.dumps(rec, ensure_ascii=False), _cap(cap))
            return rec
        except Exception:
            return None


def _self_test() -> int:
    ms = 1_000_000
    tt = TurnTimer(path="batch")
    tt.mark("capture_end", ns=0)
    tt.mark("tts_request", ns=100 * ms)
    tt.mark("tts_first_audio", ns=150 * ms)
    tt.mark("play_start", ns=200 * ms)
    tt.context(tts_backend="kokoro", preset="voice", transcript="LEAK", reply="LEAK")
    rec = tt.record(ts=None)
    assert rec["perceived_ms"] == 200.0
    assert rec["tts_ttfa_ms"] == 50.0
    assert rec["llm_ttft_ms"] is None
    assert rec["tts_backend"] == "kokoro" and rec["preset"] == "voice"
    assert "LEAK" not in json.dumps(rec)
    # disabled → no write, no raise
    os.environ["AIPC_VOICE_TIMING"] = "0"
    assert tt.flush(path="/nonexistent/should-not-write.jsonl") is None
    os.environ.pop("AIPC_VOICE_TIMING", None)
    # unwritable path → swallowed
    assert tt.flush(path=str(Path(__file__) / "nope" / "x.jsonl")) is None
    print("aipc_voice_timing: self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
