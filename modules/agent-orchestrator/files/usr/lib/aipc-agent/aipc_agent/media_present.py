"""Generic multi-media presentation for tool answers.

Not topic-specific (not typhoon-only). When tools open pages that expose
images, maps, video, PDFs, or other media, the reply should list them so the
voice HUD can show a composite set of links (and image URLs where possible).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# URL that is likely media or a media-heavy product page
_MEDIA_EXT = re.compile(
    r"\.(png|jpe?g|gif|webp|svg|mp4|webm|pdf|m3u8)(?:\?|$)",
    re.I,
)
_MAP_OR_MEDIA_HOST = re.compile(
    r"(cwa\.gov|weather|typhoon|radar|satellite|map|gis|zoom\.earth|windy|"
    r"youtube|youtu\.be|imgur|cdn\.|static\.|assets\.)",
    re.I,
)
_URL_RE = re.compile(r"https?://[^\s\]\)\"'<>，。、]+", re.I)


def extract_urls(text: str) -> list[str]:
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:)")
        if u not in out:
            out.append(u)
    return out


def is_media_url(url: str) -> bool:
    u = url or ""
    if _MEDIA_EXT.search(u):
        return True
    try:
        host = urlparse(u).netloc or ""
    except Exception:
        host = ""
    if _MAP_OR_MEDIA_HOST.search(host) or _MAP_OR_MEDIA_HOST.search(u):
        return True
    # product/article pages often carry figures; still count as presentable media page
    if re.search(r"/(img|image|images|media|photo|video|map|chart|figure)/", u, re.I):
        return True
    return False


def media_score(reply: str = "", trail: str = "") -> dict[str, Any]:
    """How much multi-media is available vs shown in the user-facing reply."""
    reply_urls = extract_urls(reply)
    trail_urls = extract_urls(trail)
    reply_media = [u for u in reply_urls if is_media_url(u)]
    trail_media = [u for u in trail_urls if is_media_url(u)]
    # also treat any URL in reply as presentable when trail had media
    hosts = set()
    for u in reply_urls:
        try:
            hosts.add((urlparse(u).netloc or "").lower())
        except Exception:
            pass
    return {
        "reply_urls": len(reply_urls),
        "trail_urls": len(trail_urls),
        "reply_media": len(reply_media),
        "trail_media": len(trail_media),
        "unique_hosts": len(hosts),
        "reply_media_list": reply_media[:12],
        "trail_media_list": trail_media[:12],
    }


def presentation_procedure() -> str:
    """Process teaching injected into Hermes for any tool-using turn."""
    return (
        "MULTI-MEDIA PRESENTATION (always, any topic — not typhoon-only):\n"
        "When tools open pages or return images/maps/video/PDF:\n"
        "1) Collect useful media URLs (maps, charts, photos, satellite, video, PDF).\n"
        "2) Prefer 2+ distinct media items when tools found them "
        "(different hosts or different product views).\n"
        "3) REPLY SHAPE for the voice HUD:\n"
        "   - Short spoken synthesis (2–5 sentences) in the user's language\n"
        "   - Then a media block, each line: · short label + full https:// URL\n"
        "4) Only list URLs you actually opened or that appear in tool output.\n"
        "5) Do not invent media. If tools found none, skip the media block.\n"
        "6) Site choice is task-driven: pick whatever sources tools surface; "
        "no single site is mandatory.\n"
    )


def missing_media_reasons(reply: str, trail: str) -> list[str]:
    """Structural reasons when trail has media but the spoken reply drops them."""
    sc = media_score(reply=reply, trail=trail)
    reasons: list[str] = []
    if sc["trail_media"] >= 1 and sc["reply_urls"] == 0:
        reasons.append("media_dropped")
    elif sc["trail_media"] >= 2 and sc["reply_urls"] < 2:
        reasons.append("thin_media_set")
    elif sc["trail_urls"] >= 2 and sc["reply_urls"] == 0:
        reasons.append("media_dropped")
    return reasons


def promote_media_from_trail(reply: str, trail: str, *, limit: int = 6) -> str:
    """Append a media list from trail URLs not already in the reply."""
    sc = media_score(reply=reply, trail=trail)
    have = {u.rstrip("/") for u in extract_urls(reply)}
    # Prefer explicit media URLs; fall back to any trail URLs
    candidates = sc["trail_media_list"] or extract_urls(trail)
    add: list[str] = []
    for u in candidates:
        key = u.rstrip("/")
        if key in have:
            continue
        if not is_media_url(u) and sc["trail_media"] > 0:
            # when we already prefer media list, skip pure junk; else allow pages
            continue
        add.append(u)
        have.add(key)
        if len(add) >= limit:
            break
    if not add and sc["trail_urls"] and sc["reply_urls"] == 0:
        for u in extract_urls(trail):
            if u.rstrip("/") in have:
                continue
            add.append(u)
            have.add(u.rstrip("/"))
            if len(add) >= limit:
                break
    if not add:
        return reply
    lines = ["\n\n（相關媒體）"]
    for u in add:
        label = "媒體"
        low = u.lower()
        if any(x in low for x in ("map", "gis", "path", "路徑", "typhoon", "颱風")):
            label = "地圖/路徑"
        elif any(x in low for x in (".png", ".jpg", ".jpeg", ".webp", "img", "image")):
            label = "圖片"
        elif any(x in low for x in (".mp4", "youtube", "video")):
            label = "影片"
        elif low.endswith(".pdf") or ".pdf" in low:
            label = "文件"
        lines.append(f"· {label} {u}")
    return (reply.rstrip() + "\n".join(lines))[:4000]
