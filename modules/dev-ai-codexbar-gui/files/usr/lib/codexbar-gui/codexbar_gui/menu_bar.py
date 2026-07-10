"""Menu-bar display logic — mirrors official CodexBar Display preferences.

Official (docs/ui.md):
- Merge Icons mode (Linux tray = always merged into one status item)
- Fill = remaining by default; “Show usage as used” flips to used %
- dual primary/secondary bars (IconRenderer)
- highest-usage auto-selection (lowest remaining)
- Overview tab providers (order / subset, up to 3 featured)
- Refresh cadence

Settings live in ``~/.config/codexbar/config.json`` under ``gui.menu_bar``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("codexbar_gui.menu_bar")

_CONFIG_CANDIDATES = (
    Path.home() / ".config" / "codexbar" / "config.json",
    Path.home() / ".codexbar" / "config.json",
)

# Provider that drives the merged tray icon
PROVIDER_SELECTION = (
    "highest_usage",  # official default-ish: most used / least remaining
    "first_enabled",  # config order
    "pinned",  # fixed provider id
)

# What the colored fill means (official: remaining default)
SHOW_AS = ("remaining", "used")

# Icon chrome style
ICON_STYLE = (
    "dual_bars",  # session + weekly capsules (official IconRenderer)
    "primary_only",  # top bar only
    "brand_percent",  # letter + % (text-ish fallback for tight panels)
)

REFRESH_PRESETS = (30, 60, 120, 300, 900)  # 30s … 15m


@dataclass
class MenuBarSettings:
    """Persisted under config.json → gui.menu_bar."""

    provider_selection: str = "highest_usage"
    pinned_provider: str = "codex"
    show_as: str = "remaining"
    icon_style: str = "dual_bars"
    overview_providers: List[str] = field(default_factory=list)
    show_percent_tooltip: bool = True
    refresh_interval: int = 60

    def normalized(self) -> "MenuBarSettings":
        sel = self.provider_selection if self.provider_selection in PROVIDER_SELECTION else "highest_usage"
        show = self.show_as if self.show_as in SHOW_AS else "remaining"
        style = self.icon_style if self.icon_style in ICON_STYLE else "dual_bars"
        ov = [str(x).lower() for x in (self.overview_providers or []) if x][:6]
        try:
            refresh = int(self.refresh_interval)
        except (TypeError, ValueError):
            refresh = 60
        refresh = max(10, min(3600, refresh))
        pin = (self.pinned_provider or "codex").lower()
        return MenuBarSettings(
            provider_selection=sel,
            pinned_provider=pin,
            show_as=show,
            icon_style=style,
            overview_providers=ov,
            show_percent_tooltip=bool(self.show_percent_tooltip),
            refresh_interval=refresh,
        )


def config_path() -> Path:
    for p in _CONFIG_CANDIDATES:
        if p.is_file():
            return p
    return _CONFIG_CANDIDATES[0]


def load_menu_bar_settings(path: Optional[Path] = None) -> MenuBarSettings:
    p = path or config_path()
    data: Dict[str, Any] = {}
    if p.is_file():
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("menu_bar settings load: %s", exc)
    gui = data.get("gui") if isinstance(data.get("gui"), dict) else {}
    mb = gui.get("menu_bar") if isinstance(gui.get("menu_bar"), dict) else {}
    # refresh_interval also lives at gui root (older saves)
    refresh = mb.get("refresh_interval", gui.get("refresh_interval", 60))
    settings = MenuBarSettings(
        provider_selection=str(mb.get("provider_selection") or "highest_usage"),
        pinned_provider=str(mb.get("pinned_provider") or "codex"),
        show_as=str(mb.get("show_as") or "remaining"),
        icon_style=str(mb.get("icon_style") or "dual_bars"),
        overview_providers=list(mb.get("overview_providers") or []),
        show_percent_tooltip=bool(mb.get("show_percent_tooltip", True)),
        refresh_interval=int(refresh) if refresh is not None else 60,
    )
    return settings.normalized()


def merge_menu_bar_into_gui(gui: Dict[str, Any], settings: MenuBarSettings) -> Dict[str, Any]:
    """Return updated gui dict for writing into config.json."""
    s = settings.normalized()
    out = dict(gui) if isinstance(gui, dict) else {}
    out["refresh_interval"] = s.refresh_interval
    out["menu_bar"] = {
        "provider_selection": s.provider_selection,
        "pinned_provider": s.pinned_provider,
        "show_as": s.show_as,
        "icon_style": s.icon_style,
        "overview_providers": list(s.overview_providers),
        "show_percent_tooltip": s.show_percent_tooltip,
        "refresh_interval": s.refresh_interval,
    }
    return out


def select_tray_view(
    views: Sequence[Any],
    settings: MenuBarSettings,
) -> Optional[Any]:
    """Pick which ProviderView drives the merged tray icon.

    Official “highest-usage auto-selection” ≈ lowest remaining % among healthy views.
    """
    s = settings.normalized()
    if not views:
        return None
    ok = [v for v in views if getattr(v, "ok", False)]
    pool = ok if ok else list(views)

    if s.provider_selection == "pinned":
        for v in pool:
            if str(getattr(v, "provider", "")).lower() == s.pinned_provider:
                return v
        return pool[0]

    if s.provider_selection == "first_enabled":
        return pool[0]

    # highest_usage
    def rem_key(v: Any) -> float:
        r = getattr(v, "headline_remaining", None)
        if r is None and getattr(v, "primary", None) is not None:
            r = getattr(v.primary, "remaining_percent", None)
        if r is None:
            return 999.0
        return float(r)

    return min(pool, key=rem_key)


def fill_from_remaining(remaining: Optional[float], show_as: str) -> Optional[float]:
    """Map remaining% → icon fill% (length of colored capsule)."""
    if remaining is None:
        return None
    rem = max(0.0, min(100.0, float(remaining)))
    if show_as == "used":
        return 100.0 - rem
    return rem


def order_overview_views(
    views: Sequence[Any],
    settings: MenuBarSettings,
) -> List[Any]:
    """Order / filter Overview cards.

    Empty overview_providers → all enabled views (config order).
    Non-empty → that order first (official “up to 3” is a soft guide; we allow more).
    """
    s = settings.normalized()
    by_id = {str(getattr(v, "provider", "")).lower(): v for v in views}
    if not s.overview_providers:
        return list(views)
    ordered: List[Any] = []
    seen = set()
    for pid in s.overview_providers:
        v = by_id.get(pid.lower())
        if v is not None and pid.lower() not in seen:
            ordered.append(v)
            seen.add(pid.lower())
    # Append remaining enabled not listed (still visible, after picks)
    for v in views:
        pid = str(getattr(v, "provider", "")).lower()
        if pid not in seen:
            ordered.append(v)
            seen.add(pid)
    return ordered


def tray_tooltip_line(
    view: Any,
    settings: MenuBarSettings,
) -> str:
    """One-line tray tip for the selected provider."""
    s = settings.normalized()
    name = getattr(view, "display_name", None) or getattr(view, "provider", "?")
    if not getattr(view, "ok", False):
        err = (getattr(view, "error", None) or "unavailable")[:80]
        return f"{name}: {err}"
    rem = getattr(view, "headline_remaining", None)
    if rem is None and getattr(view, "primary", None) is not None:
        rem = getattr(view.primary, "remaining_percent", None)
    if rem is None:
        return str(name)
    if s.show_as == "used":
        used = 100.0 - float(rem)
        pct = f"{int(round(used))}% used" if s.show_percent_tooltip else ""
    else:
        pct = f"{int(round(float(rem)))}% left" if s.show_percent_tooltip else ""
    plan = getattr(view, "plan_label", "") or ""
    bits = [str(name)]
    if plan:
        bits.append(str(plan))
    if pct:
        bits.append(pct)
    return " · ".join(bits)


def settings_as_dict(settings: MenuBarSettings) -> Dict[str, Any]:
    return asdict(settings.normalized())
