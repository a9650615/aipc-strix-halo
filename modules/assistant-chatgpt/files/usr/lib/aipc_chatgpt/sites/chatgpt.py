"""ChatGPT.com site pack — DOM automation for one site on the shared engine."""

from __future__ import annotations

from typing import Any

id = "chatgpt"
title = "ChatGPT"
url = "https://chatgpt.com/"


def login_banner_text() -> str:
    return (
        "aipc 助理：請在此完成 ChatGPT 登入。"
        "完成後終端機會自動繼續（只保存 session，不存密碼）。"
    )


def is_logged_in(page: Any) -> bool:
    info = page.evaluate(
        """() => {
          const t = document.body ? document.body.innerText : '';
          const loginHints = /登入 ChatGPT|Log in|Sign up|免費註冊|Sign up for free/i.test(t);
          const plus = /\\bPlus\\b|\\bPro\\b|Team/.test(t);
          const account = document.querySelector('[data-testid="accounts-profile-button"]');
          const composer = document.querySelector('#prompt-textarea, [contenteditable="true"]');
          return {
            loginHints,
            hasAccountButton: !!account,
            hasComposer: !!composer,
            plusHint: plus,
          };
        }"""
    )
    if info.get("loginHints") and not info.get("hasAccountButton"):
        return False
    return bool(
        info.get("hasAccountButton")
        or (info.get("hasComposer") and not info.get("loginHints"))
        or info.get("plusHint")
    )


def inject_and_send(page: Any, text: str, context_bundle: str = "") -> str:
    payload = text
    if context_bundle:
        payload = context_bundle.replace("\n", " · ") + "\n\n" + text

    composer = page.locator("#prompt-textarea").first
    if composer.count() == 0:
        composer = page.locator('[contenteditable="true"]').first
    composer.click(timeout=10000)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    page.evaluate(
        """(t) => {
          const el = document.querySelector('#prompt-textarea')
            || document.querySelector('[contenteditable="true"]');
          if (!el) return;
          el.focus();
          if (el.getAttribute('contenteditable') === 'true') {
            el.innerText = t;
            el.dispatchEvent(new InputEvent('input', { bubbles: true }));
          } else {
            el.value = t;
            el.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }""",
        payload,
    )
    page.wait_for_timeout(300)
    send = page.locator('[data-testid="send-button"]').first
    if send.count() and send.is_enabled():
        send.click(timeout=5000)
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(4000)
    try:
        bubbles = page.locator('[data-message-author-role="assistant"]')
        n = bubbles.count()
        if n:
            return bubbles.nth(n - 1).inner_text(timeout=3000)[:4000]
    except Exception:
        pass
    return "(sent; reply scrape unavailable)"


def voice_start(page: Any) -> None:
    selectors = [
        '[data-testid="composer-speech-button"]',
        'button[aria-label="開啟語音"]',
        'button[aria-label*="開啟語音"]',
        'button[aria-label*="語音"]',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                loc.click(timeout=5000)
                page.wait_for_timeout(2000)
                return
        except Exception:
            continue
    try:
        page.get_by_role("button", name="語音").first.click(timeout=5000)
        page.wait_for_timeout(2000)
        return
    except Exception as exc:
        raise RuntimeError(f"voice_start: no control ({exc})") from exc


def voice_stop(page: Any) -> None:
    for sel in (
        'button[aria-label*="結束"]',
        'button[aria-label*="關閉語音"]',
        'button[aria-label*="Stop"]',
        'button[aria-label="取消載入"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                aria = loc.get_attribute("aria-label") or ""
                if "側邊欄" in aria:
                    continue
                loc.click(timeout=3000)
                return
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
