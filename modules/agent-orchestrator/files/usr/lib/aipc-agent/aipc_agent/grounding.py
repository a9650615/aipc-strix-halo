"""Tool-grounding checks — stop inventing catalog facts without evidence.

Not a topic allowlist. Structural signals only:
  - product-style codes (ABC-123) need tool-backed facts
  - learning/skill growth requires trail or a non-homepage URL in the reply
"""

from __future__ import annotations

import re

# Product/catalog style ids: ABC-123, XY_99 (not pure integers / years)
_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{2,8})[-_ ]?(\d{2,5})(?![A-Za-z0-9])"
)
_URL_RE = re.compile(r"https?://[^\s\]\)\"'`<>]+", re.I)

# Homepage-only "links" that models invent instead of item pages
_WEAK_HOST_ONLY = re.compile(
    r"^https?://(www\.)?(fanza\.com|dmm\.co\.jp|dmm\.com|google\.com|bing\.com)/?$",
    re.I,
)


def extract_product_codes(text: str) -> list[str]:
    out: list[str] = []
    for m in _CODE_RE.finditer(text or ""):
        code = f"{m.group(1).upper()}-{m.group(2)}"
        if code not in out:
            out.append(code)
    return out


def has_product_code(text: str) -> bool:
    return bool(extract_product_codes(text))


def needs_tool_lookup(text: str) -> bool:
    """True when utterance includes a product-style code (task shape → tools)."""
    return has_product_code(text)


def _urls(text: str) -> list[str]:
    return [m.group(0).rstrip(".,;:)") for m in _URL_RE.finditer(text or "")]


def has_substantive_url(text: str) -> bool:
    """At least one URL that is not a bare retail homepage."""
    for u in _urls(text):
        if _WEAK_HOST_ONLY.match(u):
            continue
        # path or query beyond host
        if re.search(r"https?://[^/]+/.+", u) or "?" in u:
            return True
        # host with non-trivial subdomain content pages still need path —
        # bare host rejected above; multi-segment path handled
    return False


def has_tool_grounding(*, reply: str = "", trail: str = "") -> bool:
    """Evidence of a real page/item (URL), not tool-call chatter alone.

    Calling web_search without a returned URL is not enough — models still invent.
    """
    tr = (trail or "").strip()
    if tr and ("http://" in tr.lower() or "https://" in tr.lower()):
        # Prefer non-homepage URLs from trail when present
        if has_substantive_url(tr) or has_substantive_url(reply or ""):
            return True
        # trail has any http — accept if reply also cites a non-weak URL
        if has_substantive_url(reply or ""):
            return True
        # Accept trail item URLs even when reply is short voice text
        for u in _urls(tr):
            if not _WEAK_HOST_ONLY.match(u):
                return True
    if has_substantive_url(reply or ""):
        return True
    return False


def is_ungrounded_lookup(
    user: str, reply: str, *, trail: str = ""
) -> bool:
    """User asked about a product code but answer has no tool/URL evidence."""
    if not needs_tool_lookup(user or ""):
        return False
    if has_tool_grounding(reply=reply or "", trail=trail or ""):
        return False
    return True


def should_learn(
    user: str,
    reply: str,
    *,
    kind: str,
    trail: str = "",
) -> bool:
    """Skill growth only when the turn is grounded for fact lookups.

    - respond + product code → never learn (chat invents)
    - product code without trail/URL → never learn
    """
    kind = (kind or "").strip().lower()
    if kind in ("canned", "clarify"):
        return False
    if needs_tool_lookup(user):
        if kind in ("respond", "chat", ""):
            return False
        if not has_tool_grounding(reply=reply, trail=trail):
            return False
    return True
