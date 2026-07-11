"""Isolated browser profile for agent crawl / skill-learning.

When Hermes needs to browse the open web (research, catalog lookup, learning
how a site works), use a dedicated Chromium user-data dir under
/var/lib/aipc-agent/browser-sandbox — never the user's personal browser
profile and never the aipc git tree.

Process only: this module prepares paths + env. Hermes/agent-browser owns
the actual browser binary.

Policy (no topic / keyword allowlists):
  AIPC_HERMES_BROWSER=auto  → equip browser toolset on Hermes turns
                              (classifier already chose Hermes; model
                              decides whether to *call* the tools)
  =1|always                 → always equip
  =0|off                    → never equip
"""

from __future__ import annotations

import os
from pathlib import Path

# Isolated profile root (persistent on the machine, not in git)
SANDBOX_ROOT = Path(
    os.environ.get("AIPC_BROWSER_SANDBOX", "/var/lib/aipc-agent/browser-sandbox")
)

# Default ON (auto): equip browser toolset on Hermes turns. Model decides use.
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


def needs_browser(text: str = "", *, long_task: bool = False, force: bool = False) -> bool:
    """Whether this Hermes turn should equip the browser toolset.

    No string/topic matching. Hermes is already model-routed; equip tools by
    env policy. Pure greet/offline chat never reaches this path (respond node).
    Chromium starts only when Hermes actually calls a browser tool.
    """
    if MODE in ("0", "false", "no", "off"):
        return False
    if force or MODE in ("1", "true", "on", "always"):
        return True
    # auto: equip on every Hermes turn (or long_task). Model chooses use.
    if long_task:
        return True
    return bool((text or "").strip())


def hermes_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Env overlay so agent-browser / Chromium use the sandbox profile."""
    env = dict(base or os.environ)
    root = ensure_profile()
    env.setdefault("AIPC_BROWSER_SANDBOX", str(root))
    if "AGENT_BROWSER_ARGS" not in env:
        env["AGENT_BROWSER_ARGS"] = (
            "--no-sandbox,--disable-dev-shm-usage,--disable-gpu"
        )
    env.setdefault(
        "AGENT_BROWSER_ENGINE", os.environ.get("AGENT_BROWSER_ENGINE", "local")
    )
    sock = root / "sockets"
    try:
        sock.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    env.setdefault("AGENT_BROWSER_SOCKET_DIR", str(sock))
    env.setdefault(
        "BROWSER_INACTIVITY_TIMEOUT",
        os.environ.get("BROWSER_INACTIVITY_TIMEOUT", "120"),
    )
    return env


def hermes_toolsets_extra(text: str = "", *, long_task: bool = False) -> list[str]:
    """Toolsets to append when browser sandbox is equipped."""
    if not needs_browser(text, long_task=long_task):
        return []
    return ["browser"]


def prompt_hint() -> str:
    return (
        "Browser sandbox is available (isolated profile under "
        f"{SANDBOX_ROOT}). "
        "When external facts are needed: use web_search and/or open search "
        "engines in the browser (DuckDuckGo, Brave, Bing, Google, SearXNG). "
        "Side paths OK (any result site that has the facts). Prefer hosts "
        "listed in local skills when present — those were learned on this PC. "
        "browser_navigate → browser_snapshot; do not invent titles or URLs. "
        "If blocked, try another engine/result. Successful paths are merged "
        "into the local skill tree after the turn (self-learn)."
    )
