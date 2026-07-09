"""Site pack protocol — one implementation per website."""

from __future__ import annotations

from typing import Any, Protocol


class SitePack(Protocol):
    id: str
    title: str
    url: str

    def is_logged_in(self, page: Any) -> bool:
        """Return True if the page shows an authenticated session."""
        ...

    def inject_and_send(self, page: Any, text: str, context_bundle: str = "") -> str:
        ...

    def voice_start(self, page: Any) -> None:
        ...

    def voice_stop(self, page: Any) -> None:
        ...

    def login_banner_text(self) -> str:
        """Shown in-page during interactive auth."""
        ...
