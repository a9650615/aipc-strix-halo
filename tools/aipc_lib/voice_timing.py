"""Read side of voice turn-latency records (openspec: voice-latency-instrumentation).

Minimal by design: tail the JSONL log written by aipc_voice_timing.TurnTimer and
average the three headline durations. No percentiles, no per-scenario grouping —
that analytics layer is a separate, deferred change. The only contract shared
with the writer is the on-disk JSON shape.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HEADLINE = ("perceived_ms", "llm_ttft_ms", "tts_ttfa_ms")


def default_log_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "aipc-voice" / "turns.jsonl"


def read_records(path: str | os.PathLike | None = None, last: int | None = None) -> list[dict]:
    """Load turn records, skipping malformed lines; empty list if none/missing."""
    p = Path(path) if path else default_log_path()
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    if last is not None and last > 0:
        out = out[-last:]
    return out


def means(records: list[dict]) -> dict[str, float | None]:
    acc: dict[str, list[float]] = {k: [] for k in HEADLINE}
    for r in records:
        for k in HEADLINE:
            v = r.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                acc[k].append(float(v))
    return {k: (round(sum(v) / len(v), 1) if v else None) for k, v in acc.items()}


def _fmt_ms(v: object) -> str:
    return f"{v:.0f}ms" if isinstance(v, (int, float)) and not isinstance(v, bool) else "-"


def _fmt_row(r: dict) -> str:
    return (
        f"{str(r.get('path', '?')):6} "
        f"perceived={_fmt_ms(r.get('perceived_ms')):>8} "
        f"llm_ttft={_fmt_ms(r.get('llm_ttft_ms')):>8} "
        f"tts_ttfa={_fmt_ms(r.get('tts_ttfa_ms')):>8} "
        f"[{r.get('tts_backend') or '-'}/{r.get('preset') or '-'}]"
    )


def format_report(records: list[dict], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(
            {"count": len(records), "mean": means(records), "turns": records},
            ensure_ascii=False,
            indent=2,
        )
    if not records:
        return "no data (no turn records yet)"
    lines = [_fmt_row(r) for r in records]
    m = means(records)
    lines.append("")
    lines.append(
        f"mean over {len(records)} turn(s): "
        f"perceived={_fmt_ms(m['perceived_ms'])} "
        f"llm_ttft={_fmt_ms(m['llm_ttft_ms'])} "
        f"tts_ttfa={_fmt_ms(m['tts_ttfa_ms'])}"
    )
    return "\n".join(lines)
