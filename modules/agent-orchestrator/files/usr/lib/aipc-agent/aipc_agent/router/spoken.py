"""Full result vs short spoken summary (voice must not cap worker output)."""

from __future__ import annotations

import os
import re
from typing import Any


def spoken_summary(text: str, max_chars: int | None = None) -> str:
    """Bounded speech string; never used to truncate the stored full result."""
    if max_chars is None:
        try:
            max_chars = int(os.environ.get("AIPC_VOICE_TTS_CHARS", "160"))
        except ValueError:
            max_chars = 160
    max_chars = max(40, int(max_chars))
    s = re.sub(r"[`*_#>]+", "", text or "")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    parts = re.split(r"(?<=[。！？.!?])\s*", s)
    parts = [p for p in parts if p.strip()]
    out = ""
    for p in parts[:3]:
        if len(out) + len(p) > max_chars and out:
            break
        out = (out + p).strip()
    if not out:
        out = s
    if len(out) > max_chars:
        cut = out[: max_chars - 1]
        for sep in ("。", "！", "？", ".", "!", "?", "，", ","):
            i = cut.rfind(sep)
            if i >= max(20, max_chars // 3):
                return cut[: i + 1]
        out = cut.rstrip("，,、;； ") + "。"
    return out


def package_result(
    full_text: str,
    *,
    artifacts: list[Any] | None = None,
    sources: list[str] | None = None,
    verification: list[str] | None = None,
    spoken: str | None = None,
) -> dict[str, Any]:
    """Canonical task result: full body kept separate from speech."""
    body = (full_text or "").strip()
    return {
        "text": body,
        "full_text": body,
        "spoken_summary": spoken if spoken is not None else spoken_summary(body),
        "artifacts": list(artifacts or []),
        "sources": list(sources or []),
        "verification": list(verification or []),
    }
