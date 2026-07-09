"""ChatGPT Projects navigation pack (best-effort DOM)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def open_projects_home(page: Any) -> None:
    page.goto("https://chatgpt.com/projects", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(800)


def open_project_by_name(page: Any, name: str) -> str:
    """Click a project link whose text contains name, or search page text."""
    open_projects_home(page)
    # Try link role
    try:
        loc = page.get_by_role("link", name=name)
        if loc.count():
            loc.first.click(timeout=5000)
            page.wait_for_timeout(1000)
            return page.url
    except Exception:
        pass
    # Fallback: any element with text
    try:
        page.locator(f"text={name}").first.click(timeout=5000)
        page.wait_for_timeout(1000)
        return page.url
    except Exception as exc:
        raise RuntimeError(f"project not found: {name!r} ({exc})") from exc


def new_chat_in_project(page: Any) -> None:
    for sel in (
        'a[href*="/g/"]',
        'button:has-text("新對話")',
        'button:has-text("New chat")',
        '[data-testid="create-new-chat-button"]',
    ):
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                loc.click(timeout=4000)
                return
        except Exception:
            continue
