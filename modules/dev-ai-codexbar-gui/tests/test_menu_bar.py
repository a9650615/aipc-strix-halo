"""Menu-bar display selection (official Display prefs)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

GUI = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI))


@dataclass
class _Win:
    remaining_percent: float


@dataclass
class _V:
    provider: str
    ok: bool = True
    primary: Optional[_Win] = None
    error: Optional[str] = None
    plan_label: str = ""

    @property
    def display_name(self) -> str:
        return self.provider.title()

    @property
    def headline_remaining(self) -> Optional[float]:
        return self.primary.remaining_percent if self.primary else None


def test_select_highest_usage() -> None:
    from codexbar_gui.menu_bar import MenuBarSettings, select_tray_view

    views = [
        _V("codex", primary=_Win(90)),
        _V("claude", primary=_Win(20)),
        _V("zai", primary=_Win(50)),
    ]
    s = MenuBarSettings(provider_selection="highest_usage")
    pick = select_tray_view(views, s)
    assert pick is not None
    assert pick.provider == "claude"


def test_select_pinned() -> None:
    from codexbar_gui.menu_bar import MenuBarSettings, select_tray_view

    views = [
        _V("codex", primary=_Win(10)),
        _V("zai", primary=_Win(90)),
    ]
    s = MenuBarSettings(provider_selection="pinned", pinned_provider="zai")
    pick = select_tray_view(views, s)
    assert pick is not None
    assert pick.provider == "zai"


def test_fill_show_as_used() -> None:
    from codexbar_gui.menu_bar import fill_from_remaining

    assert fill_from_remaining(80.0, "remaining") == 80.0
    assert fill_from_remaining(80.0, "used") == 20.0
    assert fill_from_remaining(None, "used") is None


def test_order_overview() -> None:
    from codexbar_gui.menu_bar import MenuBarSettings, order_overview_views

    views = [_V("codex"), _V("claude"), _V("zai")]
    s = MenuBarSettings(overview_providers=["zai", "codex"])
    ordered = order_overview_views(views, s)
    assert [v.provider for v in ordered] == ["zai", "codex", "claude"]


def test_load_save_roundtrip(tmp_path) -> None:
    from codexbar_gui.menu_bar import (
        MenuBarSettings,
        load_menu_bar_settings,
        merge_menu_bar_into_gui,
    )
    import json

    p = tmp_path / "config.json"
    s = MenuBarSettings(
        provider_selection="pinned",
        pinned_provider="grok",
        show_as="used",
        icon_style="primary_only",
        overview_providers=["codex", "claude"],
        refresh_interval=120,
    )
    data = {"version": 1, "providers": [], "gui": merge_menu_bar_into_gui({}, s)}
    p.write_text(json.dumps(data))
    loaded = load_menu_bar_settings(p)
    assert loaded.provider_selection == "pinned"
    assert loaded.pinned_provider == "grok"
    assert loaded.show_as == "used"
    assert loaded.icon_style == "primary_only"
    assert loaded.overview_providers == ["codex", "claude"]
    assert loaded.refresh_interval == 120
