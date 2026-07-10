"""Isolated browser profile for agent crawl / skill-learning.

When Hermes needs to browse the open web (research, catalog lookup, learning
how a site works), use a dedicated Chromium user-data dir under
/var/lib/aipc-agent/browser-sandbox — never the user's personal browser
profile and never the aipc git tree.

Process only: this module prepares paths + env. Hermes/agent-browser owns
the actual browser binary.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Isolated profile root (persistent on the machine, not in git)
SANDBOX_ROOT = Path(
    os.environ.get("AIPC_BROWSER_SANDBOX", "/var/lib/aipc-agent/browser-sandbox")
)

# auto | 1 | always | 0 | off
MODE = (os.environ.get("AIPC_HERMES_BROWSER", "auto") or "auto").lower()


def ensure_profile() -> Path:
    """Create sandbox profile dir (0700). Returns path (best-effort)."""
    try:
        SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        os.chmod(SANDBOX_ROOT, 0o700)
    except OSError as exc:
        print(f"aipc-agent: browser-sandbox mkdir: {exc}", flush=True)
    marker = SANDBOX_ROOT / "README.aipc"
    if SANDBOX_ROOT.is_dir() and not marker.is_file():
        try:
            marker.write_text(
                "AIPC agent browser sandbox profile (Playwright/agent-browser).\n"
                "Isolated from personal Chrome/Firefox profiles.\n"
                "Used when Hermes needs to crawl for research or skill learning.\n"
                "Not part of the aipc git skill tree.\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return SANDBOX_ROOT


def needs_browser(text: str, *, long_task: bool = False, force: bool = False) -> bool:
    """Whether this Hermes turn should enable the browser toolset.

    Model-first intent still chooses Hermes; this only decides whether to
    equip the browser sandbox for that run. No topic allowlists — only
    task shape (web research / multi-step browse / explicit force).
    """
    if MODE in ("0", "false", "no", "off"):
        return False
    if force or MODE in ("1", "true", "on", "always"):
        return True
    # auto
    if long_task:
        return True
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    # Task-shape cues: lookup / browse / open URL / scrape / research page
    if re.search(r"https?://", raw):
        return True
    webish = (
        "浏览",
        "瀏覽",
        "打开网页",
        "打開網頁",
        "网站",
        "網站",
        "爬",
        "抓取",
        "browser",
        "playwright",
        "网页",
        "網頁",
        "搜一下",
        "搜尋",
        "搜索",
        "查一下",
        "查找",
        "番号",  # catalog codes often need site browse
        "web search",
        "look up",
        "lookup",
        "scrape",
        "crawl",
    )
    if any(k in raw or k in low for k in webish):
        return True
    # Local skill body may teach "use browser" — caller can force via env
    return False


def hermes_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Env overlay so agent-browser / Chromium use the sandbox profile."""
    env = dict(base or os.environ)
    root = ensure_profile()
    # agent-browser / playwright conventions used by Hermes browser_tool
    env.setdefault("AIPC_BROWSER_SANDBOX", str(root))
    # Common Chromium isolation flags when running headless as service user
    if "AGENT_BROWSER_ARGS" not in env:
        env["AGENT_BROWSER_ARGS"] = (
            "--no-sandbox,--disable-dev-shm-usage,--disable-gpu"
        )
    # Prefer local engine over cloud Browserbase unless user configured otherwise
    env.setdefault("AGENT_BROWSER_ENGINE", os.environ.get("AGENT_BROWSER_ENGINE", "local"))
    # Socket dir for daemon isolation per agent host
    sock = root / "sockets"
    try:
        sock.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    env.setdefault("AGENT_BROWSER_SOCKET_DIR", str(sock))
    env.setdefault("BROWSER_INACTIVITY_TIMEOUT", os.environ.get("BROWSER_INACTIVITY_TIMEOUT", "120"))
    return env


def hermes_toolsets_extra(text: str, *, long_task: bool = False) -> list[str]:
    """Toolsets to append when browser sandbox is needed."""
    if not needs_browser(text, long_task=long_task):
        return []
    # browser toolset includes web_search + navigate/click/snapshot
    return ["browser"]


def prompt_hint() -> str:
    return (
        "Browser sandbox is enabled (isolated profile under "
        f"{SANDBOX_ROOT}). Discover the lookup path yourself: "
        "web_search the query/code, open promising result pages with "
        "browser_navigate + browser_snapshot, extract title/cast/URL. "
        "Your short final answer must use what tools found (title + URL). "
        "On-box skill learning will later capture the procedure so next time "
        "you follow that path faster — not a one-shot memorized answer."
    )
