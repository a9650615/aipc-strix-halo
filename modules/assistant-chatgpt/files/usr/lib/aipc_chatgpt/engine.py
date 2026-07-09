"""Shared Playwright Chromium engine — one process, many site packs."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any

from aipc_chatgpt.paths import cdp_port, profile_dir, storage_state_path
from aipc_chatgpt.sites import registry as site_registry


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


class WebEngine:
    """Multi-site browser host. Site-specific DOM lives in sites/* packs."""

    def __init__(self, site_id: str | None = None, *, force_headed: bool = False) -> None:
        self.cfg = site_registry.load_sites_config()
        self.site_id = site_id or site_registry.default_site_id(self.cfg)
        self.site_cfg = site_registry.get_site_config(self.site_id, self.cfg)
        self.pack = site_registry.load_pack(self.site_id, self.cfg)
        self.url = str(self.site_cfg.get("url") or getattr(self.pack, "url", ""))
        self.force_headed = force_headed
        self._headless = True
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def available(self) -> bool:
        try:
            import playwright  # noqa: F401

            return True
        except ImportError:
            return False

    def status(self) -> dict[str, Any]:
        st = storage_state_path(self.site_id)
        out: dict[str, Any] = {
            "available": self.available(),
            "site_id": self.site_id,
            "site_title": self.site_cfg.get("title") or self.site_id,
            "url": self.url,
            "profile": str(profile_dir(self.site_id)),
            "storage_state": str(st),
            "storage_state_present": st.is_file(),
            "cdp_port": cdp_port(),
            "cdp_up": _port_open(cdp_port()),
            "engine": "playwright-chromium",
            "headless": bool(getattr(self, "_headless", True)),
            "sites_enabled": site_registry.list_site_ids(self.cfg),
            # Do NOT open a browser just to check login — steals desktop focus.
            "logged_in": True if st.is_file() and st.stat().st_size > 50 else None,
        }
        return out

    def _ensure_browser(self) -> None:
        if not self.available():
            raise RuntimeError(
                "playwright not installed (pip install playwright && "
                "python -m playwright install chromium)"
            )
        from playwright.sync_api import sync_playwright

        port = int((self.cfg.get("engine") or {}).get("cdp_port") or cdp_port())
        if self._browser is not None or self._context is not None:
            return

        # Only reuse an existing CDP browser when explicitly requested.
        # Auto-attach used to steal focus from whatever was already on :9222.
        reuse = os.environ.get("AIPC_WEB_CDP_REUSE", "").strip() in ("1", "true", "yes")
        if reuse and _port_open(port):
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctxs = self._browser.contexts
            self._context = ctxs[0] if ctxs else self._browser.new_context()
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
            self._headless = not bool(getattr(self, "force_headed", False))
            return

        profile = profile_dir(self.site_id)
        profile.mkdir(parents=True, exist_ok=True)
        eng = self.cfg.get("engine") or {}
        # Headless by default — never steal the user's desktop during tests.
        # Force headed only when: AIPC_WEB_HEADED=1, or eng.headless false,
        # or caller set self.force_headed (auth login).
        env_headed = os.environ.get("AIPC_WEB_HEADED", "").strip() in ("1", "true", "yes")
        force = bool(getattr(self, "force_headed", False))
        headless = not force and not env_headed and bool(eng.get("headless", True))
        self._pw = sync_playwright().start()
        args = [
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--disable-translate",
        ]
        # --app= is mainly for headed chrome app window chrome
        if not headless:
            args.append(f"--app={self.url}")
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            args=args,
            viewport={"width": 1280, "height": 900},
            locale=str(eng.get("locale") or "zh-TW"),
        )
        self._headless = headless
        self._browser = self._context.browser
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        if self.url and self.url not in (self._page.url or ""):
            self._page.goto(self.url, wait_until="domcontentloaded", timeout=60000)

    def _page_ready(self):
        self._ensure_browser()
        assert self._page is not None
        # Never bring_to_front in headless/automation — steals desktop focus
        if not getattr(self, "_headless", True):
            try:
                self._page.bring_to_front()
            except Exception:
                pass
        if self.url and self.url.split("/")[2] not in (self._page.url or ""):
            self._page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
        self._page.wait_for_timeout(600)
        return self._page

    def inject_and_send(self, text: str, context_bundle: str = "") -> str:
        page = self._page_ready()
        return self.pack.inject_and_send(page, text, context_bundle=context_bundle)

    def turn_voice(self, context_bundle: str = "") -> None:
        page = self._page_ready()
        if context_bundle:
            try:
                self.pack.inject_and_send(
                    page,
                    "（系統上下文，請簡短確認收到即可，然後等待語音。）",
                    context_bundle=context_bundle,
                )
            except Exception:
                pass
            page = self._page_ready()
        self.pack.voice_start(page)

    def voice_stop(self) -> None:
        if self._page is None:
            return
        self.pack.voice_stop(self._page)

    def session_close(self) -> None:
        try:
            self.auth_export()
        except Exception:
            pass
        for attr in ("_page", "_context", "_pw"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                if attr == "_pw":
                    obj.stop()
                else:
                    obj.close()
            except Exception:
                pass
            setattr(self, attr, None)
        self._browser = None

    def auth_status(self) -> dict[str, Any]:
        try:
            page = self._page_ready()
        except Exception as exc:
            st = storage_state_path(self.site_id)
            return {
                "site_id": self.site_id,
                "logged_in": None,
                "error": str(exc),
                "storage_state_present": st.is_file(),
            }
        logged = bool(self.pack.is_logged_in(page))
        return {
            "site_id": self.site_id,
            "logged_in": logged,
            "url": page.url,
            "storage_state_present": storage_state_path(self.site_id).is_file(),
            "profile": str(profile_dir(self.site_id)),
        }

    def auth_login(self, timeout_s: int = 300) -> dict[str, Any]:
        """Interactive login only — forces a visible (headed) window."""
        if self._context is not None and getattr(self, "_headless", True):
            try:
                self.session_close()
            except Exception:
                pass
        self.force_headed = True
        page = self._page_ready()
        page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
        banner = self.pack.login_banner_text()
        try:
            page.evaluate(
                """(msg) => {
                  let b = document.getElementById('aipc-login-banner');
                  if (!b) {
                    b = document.createElement('div');
                    b.id = 'aipc-login-banner';
                    Object.assign(b.style, {
                      position: 'fixed', top: '0', left: '0', right: '0', zIndex: '99999',
                      background: '#0b57d0', color: '#fff', padding: '10px 16px',
                      font: '14px system-ui,sans-serif', textAlign: 'center',
                    });
                    document.body.appendChild(b);
                  }
                  b.textContent = msg;
                }""",
                banner,
            )
        except Exception:
            pass
        deadline = time.time() + max(30, timeout_s)
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.auth_status()
            if last.get("logged_in"):
                try:
                    page.evaluate(
                        """() => {
                          const b = document.getElementById('aipc-login-banner');
                          if (b) {
                            b.textContent = '登入成功 — session 已保存。';
                            b.style.background = '#0d7a3f';
                          }
                        }"""
                    )
                except Exception:
                    pass
                path = self.auth_export()
                last["exported"] = str(path)
                last["message"] = "logged in; storage_state saved"
                return last
            page.wait_for_timeout(2000)
        last = self.auth_status()
        last["message"] = "timeout — complete login and re-run auth login / setup --online"
        return last

    def auth_export(self, dest: Path | None = None) -> Path:
        page = self._page_ready()
        assert self._context is not None
        path = dest or storage_state_path(self.site_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = self._context.storage_state()
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path

    def auth_import(self, src: Path | None = None) -> Path:
        path = src or storage_state_path(self.site_id)
        if not path.is_file():
            raise FileNotFoundError(f"no storage_state at {path}")
        state = json.loads(path.read_text(encoding="utf-8"))
        page = self._page_ready()
        assert self._context is not None
        cookies = state.get("cookies") or []
        clean = []
        for c in cookies:
            if not isinstance(c, dict) or "name" not in c:
                continue
            item = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain") or "",
                "path": c.get("path") or "/",
            }
            if c.get("expires", -1) not in (-1, None):
                item["expires"] = c["expires"]
            for k in ("httpOnly", "secure", "sameSite"):
                if c.get(k) is not None:
                    item[k] = c[k]
            if item["domain"]:
                clean.append(item)
        if clean:
            self._context.add_cookies(clean)
        page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)
        return path
