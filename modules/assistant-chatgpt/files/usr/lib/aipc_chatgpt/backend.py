"""Facade for aggregator: multi-site web engine, default site from config."""

from __future__ import annotations

from typing import Any

from aipc_chatgpt.engine import WebEngine
from aipc_chatgpt.sites import registry as site_registry


class PlaywrightBackend:
    """Backward-compatible name: actually multi-site WebEngine wrapper."""

    def __init__(self, site_id: str | None = None, *, force_headed: bool = False) -> None:
        self._site_id = site_id
        self._force_headed = force_headed
        self._engine: WebEngine | None = None

    def _eng(self) -> WebEngine:
        if self._engine is None:
            self._engine = WebEngine(self._site_id, force_headed=self._force_headed)
        return self._engine

    def available(self) -> bool:
        return self._eng().available()

    def status(self) -> dict[str, Any]:
        return self._eng().status()

    def inject_and_send(self, text: str, context_bundle: str = "") -> str:
        return self._eng().inject_and_send(text, context_bundle=context_bundle)

    def turn_voice(self, context_bundle: str = "") -> None:
        return self._eng().turn_voice(context_bundle=context_bundle)

    def voice_stop(self) -> None:
        return self._eng().voice_stop()

    def session_close(self) -> None:
        return self._eng().session_close()

    def auth_status(self) -> dict[str, Any]:
        return self._eng().auth_status()

    def auth_login(self, timeout_s: int = 300) -> dict[str, Any]:
        # Always headed for human login
        if self._engine is not None and getattr(self._engine, "_headless", True):
            try:
                self._engine.session_close()
            except Exception:
                pass
            self._engine = None
        self._force_headed = True
        return self._eng().auth_login(timeout_s=timeout_s)

    def auth_export(self, dest=None):
        return self._eng().auth_export(dest)

    def auth_import(self, src=None):
        return self._eng().auth_import(src)

    def use_site(self, site_id: str) -> None:
        """Switch site pack (new engine instance)."""
        if self._engine is not None:
            try:
                self._engine.session_close()
            except Exception:
                pass
        self._site_id = site_id
        self._engine = WebEngine(site_id)


def get_backend(site_id: str | None = None) -> PlaywrightBackend:
    return PlaywrightBackend(site_id or site_registry.default_site_id())
