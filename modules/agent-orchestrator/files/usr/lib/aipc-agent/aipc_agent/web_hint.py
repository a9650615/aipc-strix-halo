"""Fast on-box web search hints for Hermes / chat (DuckDuckGo Lite scrape).

Generic process — not topic-gated. Used when the user needs titles, details,
or watch/catalog links and Hermes' own search is blocked or slow.

Results are injected as context; the model still judges what to say.
"""

from __future__ import annotations

import html as html_mod
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ENABLED = os.environ.get("AIPC_WEB_HINT", "1") not in ("0", "false", "no", "off")
TIMEOUT = float(os.environ.get("AIPC_WEB_HINT_TIMEOUT", "14"))
MAX_RESULTS = int(os.environ.get("AIPC_WEB_HINT_MAX", "5"))
UA = os.environ.get(
    "AIPC_WEB_HINT_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
)


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def search_ddg_lite(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    """Return [{title, url, snippet}] from DuckDuckGo Lite HTML."""
    if not ENABLED or not (query or "").strip():
        return []
    limit = limit or MAX_RESULTS
    q = query.strip()[:200]
    url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": q})
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"aipc-agent: web_hint ddg fail: {exc}", flush=True)
        return []

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    # Each hit: nearby text + uddg=URL
    for m in re.finditer(r".{0,280}uddg=([^&\"']+).{0,120}", data):
        raw_u = urllib.parse.unquote(m.group(1))
        if not raw_u.startswith("http"):
            continue
        if raw_u in seen:
            continue
        # skip duckduckgo internals
        if "duckduckgo.com" in raw_u:
            continue
        ctx = m.group(0)
        titles = re.findall(r">([^<>]{8,160})<", ctx)
        title = ""
        for t in titles:
            t = html_mod.unescape(t).strip()
            if not t or "http" in t.lower() or t.startswith("..."):
                continue
            if re.fullmatch(r"[\d\W]+", t):
                continue
            title = t
            break
        if not title:
            title = raw_u.split("/")[-2] if raw_u.endswith("/") else raw_u.rsplit("/", 1)[-1]
            title = urllib.parse.unquote(title)[:120]
        seen.add(raw_u)
        out.append({"title": title[:200], "url": raw_u[:300], "snippet": ""})
        if len(out) >= limit:
            break
    return out


# Back-compat alias used by tests / callers
def search_bing(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    return search_ddg_lite(query, limit=limit)


def format_hints(results: list[dict[str, str]]) -> str:
    if not results:
        return ""
    lines = [
        "Web search hits (use for title / cast / watch-or-catalog links; "
        "prefer concrete facts over generic advice):"
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title')}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:160]}")
        lines.append(f"   URL: {r.get('url')}")
    return "\n".join(lines)


def hints_for(query: str, *, limit: int = 0) -> str:
    return format_hints(search_ddg_lite(query, limit=limit))


def lookup_wants_web(text: str) -> bool:
    """Task-shape: user wants find/search/lookup info (not pure chitchat)."""
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    keys = (
        "查",
        "搜",
        "找",
        "番号",
        "片名",
        "链接",
        "連結",
        "在线",
        "在線",
        "watch",
        "lookup",
        "search",
        "http://",
        "https://",
        "什么片子",
        "什麼片子",
        "是什么",
        "是什麼",
        "a片",
        "A片",
    )
    if any(k in raw or k in low for k in keys):
        return True
    if re.search(r"(?i)\b[A-Z]{2,5}-?\d{2,5}\b", raw):
        return True
    return False
