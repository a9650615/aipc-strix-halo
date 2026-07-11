"""On-box multi-engine search hints for Hermes cold-start.

Not topic-gated. Generic search engines only (no per-site catalog hardcodes):
  1. Local SearXNG (AIPC_SEARXNG_ENDPOINT, default :8888) when up
  2. DuckDuckGo Lite/HTML
  3. Brave Search HTML
  4. Bing HTML

Site-specific paths (e.g. a catalog that worked once) belong in **local skills**
after path-harvest — not in this process. Results are context; model must not invent.
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
TIMEOUT = float(os.environ.get("AIPC_WEB_HINT_TIMEOUT", "12"))
MAX_RESULTS = int(os.environ.get("AIPC_WEB_HINT_MAX", "6"))
SEARX = os.environ.get("AIPC_SEARXNG_ENDPOINT", "http://127.0.0.1:8888").rstrip("/")
UA = os.environ.get(
    "AIPC_WEB_HINT_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
)

_HREF_RE = re.compile(
    r'href=["\'](https?://[^"\']+)["\'][^>]*>([^<]{0,200})',
    re.I,
)


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8,ja;q=0.7",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _is_junk_url(u: str) -> bool:
    low = (u or "").lower()
    junk = (
        "duckduckgo.com",
        "brave.com",
        "search.brave.com",
        "cdn.search.brave",
        "bing.com/",
        "microsoft.com/",
        "google.com/search",
        "google.com/url",
        "google.com/aclk",
        "microsofttranslator",
        "javascript:",
        "accounts.google",
        "login.",
        "hackerone.com",
        "support.brave",
        "chrome.google.com",
        "play.google.com",
        "apple.com/app",
        "facebook.com/",
        "twitter.com/",
        "x.com/",
        "/feed/",
        "/rss",
        "format=xml",
    )
    return any(j in low for j in junk)


def _title_from_url(u: str) -> str:
    slug = (u or "").rstrip("/").rsplit("/", 1)[-1]
    slug = urllib.parse.unquote(slug)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return slug[:200]


def _query_tokens(query: str) -> list[str]:
    q = (query or "").strip().upper()
    toks = re.findall(
        r"[A-Z]{2,8}[-_ ]?\d{2,5}|[A-Z]{3,}|[\w\u4e00-\u9fff]{2,}", q
    )
    return [t.replace(" ", "-") for t in toks if len(t) >= 2][:8]


def _rank_hits(hits: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    """Prefer pages that look like item hits for the query code/tokens."""
    toks = _query_tokens(query)
    if not toks:
        return hits

    def score(h: dict[str, str]) -> int:
        blob = f"{h.get('title', '')} {h.get('url', '')} {h.get('snippet', '')}".upper()
        s = 0
        compact_blob = blob.replace("-", "").replace("_", "").replace(" ", "")
        for t in toks:
            t2 = t.replace("_", "-").replace(" ", "")
            if t2 in blob.replace("_", "-").replace(" ", ""):
                s += 10
            compact = t2.replace("-", "")
            if compact and compact in compact_blob:
                s += 8
        if re.search(r"/\d{4,}/", h.get("url") or ""):
            s += 1
        return s

    return sorted(hits, key=score, reverse=True)


def search_searxng(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    """Local SearXNG JSON API when the container is up."""
    limit = limit or MAX_RESULTS
    url = SEARX + "/search?" + urllib.parse.urlencode(
        {"q": query.strip()[:200], "format": "json"}
    )
    try:
        raw = _get(url)
        import json

        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: web_hint searxng fail: {exc}", flush=True)
        return []
    out: list[dict[str, str]] = []
    for hit in data.get("results") or []:
        if not isinstance(hit, dict):
            continue
        u = str(hit.get("url") or "").strip()
        t = str(hit.get("title") or "").strip()
        sn = str(hit.get("content") or hit.get("snippet") or "").strip()
        if not u.startswith("http") or _is_junk_url(u):
            continue
        out.append(
            {
                "title": (t or u)[:200],
                "url": u[:400],
                "snippet": sn[:200],
                "engine": "searxng",
            }
        )
        if len(out) >= limit:
            break
    return out


def search_ddg_lite(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    """DuckDuckGo Lite + HTML endpoints."""
    limit = limit or MAX_RESULTS
    q = query.strip()[:200]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for base in (
        "https://lite.duckduckgo.com/lite/?",
        "https://html.duckduckgo.com/html/?",
    ):
        url = base + urllib.parse.urlencode({"q": q})
        try:
            data = _get(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"aipc-agent: web_hint ddg fail: {exc}", flush=True)
            continue
        if "anomaly-modal" in data or "Select all squares" in data:
            print("aipc-agent: web_hint ddg challenge wall", flush=True)
            continue
        for m in re.finditer(r".{0,280}uddg=([^&\"']+).{0,160}", data):
            raw_u = urllib.parse.unquote(m.group(1))
            if not raw_u.startswith("http") or raw_u in seen or _is_junk_url(raw_u):
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
                title = urllib.parse.unquote(raw_u.rsplit("/", 1)[-1])[:120]
            seen.add(raw_u)
            out.append(
                {
                    "title": title[:200],
                    "url": raw_u[:400],
                    "snippet": "",
                    "engine": "ddg",
                }
            )
            if len(out) >= limit:
                return out
        # result__a style on html.duckduckgo.com
        for m in re.finditer(
            r'class="[^"]*result__a[^"]*"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            data,
            re.I | re.S,
        ):
            raw_u = html_mod.unescape(m.group(1)).strip()
            if "uddg=" in raw_u:
                um = re.search(r"uddg=([^&]+)", raw_u)
                if um:
                    raw_u = urllib.parse.unquote(um.group(1))
            title = _strip_tags(m.group(2))[:200]
            if not raw_u.startswith("http") or raw_u in seen or _is_junk_url(raw_u):
                continue
            seen.add(raw_u)
            out.append(
                {
                    "title": title or raw_u[:120],
                    "url": raw_u[:400],
                    "snippet": "",
                    "engine": "ddg",
                }
            )
            if len(out) >= limit:
                return out
    return out


def search_brave_html(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    """Brave Search HTML scrape (side-path engine)."""
    limit = limit or MAX_RESULTS
    q = query.strip()[:200]
    url = "https://search.brave.com/search?" + urllib.parse.urlencode({"q": q})
    try:
        data = _get(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"aipc-agent: web_hint brave fail: {exc}", flush=True)
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    # Prefer structured result title links
    patterns = (
        r'data-testid="result-title-a"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        r'class="[^"]*result-header[^"]*"[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        r'<a[^>]+href="(https?://[^"]+)"[^>]+class="[^"]*title[^"]*"[^>]*>(.*?)</a>',
    )
    for pat in patterns:
        for m in re.finditer(pat, data, re.I | re.S):
            raw_u = html_mod.unescape(m.group(1)).strip()
            title = _strip_tags(m.group(2))[:200]
            if not raw_u.startswith("http") or raw_u in seen or _is_junk_url(raw_u):
                continue
            seen.add(raw_u)
            out.append(
                {
                    "title": title or raw_u[:120],
                    "url": raw_u[:400],
                    "snippet": "",
                    "engine": "brave",
                }
            )
            if len(out) >= limit:
                return out
    return out


def search_bing_html(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    """Bing HTML light scrape (extra side path)."""
    limit = limit or MAX_RESULTS
    q = query.strip()[:200]
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": q})
    try:
        data = _get(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"aipc-agent: web_hint bing fail: {exc}", flush=True)
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        data,
        re.I | re.S,
    ):
        raw_u = html_mod.unescape(m.group(1)).split("&")[0].strip()
        # bing redirect
        if "bing.com/ck/" in raw_u:
            um = re.search(r"[?&]u=a1([^&]+)", raw_u)
            if um:
                try:
                    import base64

                    pad = um.group(1) + "=" * (-len(um.group(1)) % 4)
                    raw_u = base64.urlsafe_b64decode(pad).decode("utf-8", "replace")
                except Exception:
                    continue
        title = _strip_tags(m.group(2))[:200]
        if not raw_u.startswith("http") or raw_u in seen or _is_junk_url(raw_u):
            continue
        seen.add(raw_u)
        out.append(
            {
                "title": title or raw_u[:120],
                "url": raw_u[:400],
                "snippet": "",
                "engine": "bing",
            }
        )
        if len(out) >= limit:
            break
    return out


# Back-compat alias
def search_bing(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    return search_multi(query, limit=limit)


def search_multi(query: str, *, limit: int = 0) -> list[dict[str, str]]:
    """Merge multi-engine hits (order: searxng, ddg, brave, bing)."""
    if not ENABLED or not (query or "").strip():
        return []
    limit = limit or MAX_RESULTS
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    # Generic engines only — site-specific catalogs live in local skills after learn.
    engines = (
        ("searxng", search_searxng),
        ("ddg", search_ddg_lite),
        ("brave", search_brave_html),
        ("bing", search_bing_html),
    )
    for name, fn in engines:
        if len(merged) >= limit:
            break
        try:
            hits = fn(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-agent: web_hint {name} error: {exc}", flush=True)
            hits = []
        for h in hits:
            u = (h.get("url") or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            merged.append(h)
            if len(merged) >= limit:
                break
        if hits:
            print(
                f"aipc-agent: web_hint {name} hits={len(hits)} merged={len(merged)}",
                flush=True,
            )
    return _rank_hits(merged, query)[:limit]


def format_hints(results: list[dict[str, str]]) -> str:
    if not results:
        return ""
    lines = [
        "Multi-engine web search hits (any site is fine — official store, "
        "database, mirror, review page). Use title/cast/URL only if present "
        "below or after you open the page with browser tools. "
        "Do not invent cast/title if not in hits or tool output:",
    ]
    for i, r in enumerate(results, 1):
        eng = r.get("engine") or "?"
        lines.append(f"{i}. [{eng}] {r.get('title')}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:160]}")
        lines.append(f"   URL: {r.get('url')}")
    lines.append(
        "If one engine failed, still use other hits. Open promising item URLs "
        "with browser_navigate; side-path catalogs are OK."
    )
    return "\n".join(lines)


def hints_for(query: str, *, limit: int = 0) -> str:
    return format_hints(search_multi(query, limit=limit))


def hermes_hint_enabled(*, has_skill: bool = False, text: str = "") -> bool:
    """When to inject search hits into Hermes prompt.

    AIPC_WEB_HINT_HERMES:
      0/off   → never
      1/always → whenever browser equip
      auto    → default ON for product-code / no skill / always prefer search
    """
    mode = (os.environ.get("AIPC_WEB_HINT_HERMES", "auto") or "auto").lower()
    if mode in ("0", "false", "no", "off"):
        return False
    if mode in ("1", "true", "on", "always"):
        return True
    # auto: inject freely so side-paths + engines help; skill does not block
    return True
