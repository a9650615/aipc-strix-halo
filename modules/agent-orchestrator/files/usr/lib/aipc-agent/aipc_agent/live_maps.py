"""Backward-compatible exports — use media_present for new code. """

from __future__ import annotations

from aipc_agent.media_present import (  # noqa: F401
    extract_urls,
    is_media_url,
    media_score,
    missing_media_reasons,
    presentation_procedure,
    promote_media_from_trail,
)

# Deprecated typhoon-named helpers (thin wrappers)
import re

_TYPHOON_RE = re.compile(r"(台风|颱風|typhoon)", re.I)


def is_typhoon_query(text: str) -> bool:
    return bool(_TYPHOON_RE.search(text or ""))


def typhoon_tool_procedure(text: str) -> str:
    # No longer typhoon-only: general multi-media presentation
    return presentation_procedure() if is_typhoon_query(text) else presentation_procedure()


def typhoon_media_score(reply: str) -> dict:
    return media_score(reply=reply, trail="")


def typhoon_reply_needs_cwa(text: str) -> bool:
    return False  # no hard site lock
