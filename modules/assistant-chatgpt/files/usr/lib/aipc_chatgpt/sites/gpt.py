"""Custom GPT open by slug/URL (best-effort)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def open_gpt(page: Any, slug_or_url: str) -> str:
    raw = slug_or_url.strip()
    if raw.startswith("http"):
        url = raw
    elif raw.startswith("g-"):
        url = f"https://chatgpt.com/g/{quote(raw)}"
    else:
        url = f"https://chatgpt.com/g/{quote(raw)}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(800)
    return page.url
