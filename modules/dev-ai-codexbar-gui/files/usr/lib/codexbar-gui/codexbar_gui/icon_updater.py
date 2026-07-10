"""Tray icon — dual remaining capsules (official CodexBar IconRenderer style).

steipete/CodexBar ``IconRenderer.swift``:
- 18pt template, 2× → 36px canvas
- top session bar thicker, bottom weekly thinner
- fill = remaining %, left → right
- **no digit badge** on the meter (percent is menu-bar text on macOS;
  on Linux we put % in the tray tooltip / popover body only)

Plasma clips edge paint: keep a small safe pad; no dark tile behind bars.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap

logger = logging.getLogger("codexbar_gui.icon_updater")

# Logical size for StatusNotifier (Plasma scales). 22–24 works well.
DEFAULT_TRAY_SIZE = 22
OFFICIAL_CANVAS = 36.0
CREDITS_CAP = 1000.0


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _device_pixel_ratio() -> float:
    app = QGuiApplication.instance()
    if app is None:
        return 2.0
    screen = app.primaryScreen()
    if screen is None:
        return 2.0
    return max(2.0, float(screen.devicePixelRatio()))


def get_color_for_percent(percent: float) -> str:
    clamped = _clamp(percent)
    if clamped > 80:
        return "#e74c3c"
    if clamped > 50:
        return "#f39c12"
    return "#27ae60"


def get_color_for_remaining(remaining: float) -> str:
    r = _clamp(remaining)
    if r <= 20:
        return "#f7768e"
    if r <= 50:
        return "#e0af68"
    # Near-white for healthy remaining (readable on dark/light panels)
    return "#c0caf5"


def generate_svg(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = 24,
) -> str:
    del size
    if error:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">'
            '<rect x="3" y="6" width="16" height="5" rx="2.5" fill="#45475a"/>'
            '<rect x="3" y="13" width="16" height="3" rx="1.5" fill="#45475a"/>'
            "</svg>"
        )
    used = 0.0 if percent is None else _clamp(percent)
    rem = 100.0 - used
    tw = max(0, min(16, int(16 * rem / 100)))
    bw = max(0, min(16, int(16 * rem / 100)))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">'
        f'<rect x="3" y="6" width="16" height="5" rx="2.5" fill="#3b4261"/>'
        f'<rect x="3" y="6" width="{tw}" height="5" rx="2.5" fill="#c0caf5"/>'
        f'<rect x="3" y="13" width="16" height="3" rx="1.5" fill="#3b4261"/>'
        f'<rect x="3" y="13" width="{bw}" height="3" rx="1.5" fill="#a9b1d6"/>'
        f"</svg>"
    )


def svg_to_qicon_data(svg_string: str) -> str:
    import urllib.parse

    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg_string, safe="")


def _new_canvas(size: int) -> tuple[QPixmap, QPainter]:
    dpr = _device_pixel_ratio()
    phys = max(1, int(round(size * dpr)))
    pixmap = QPixmap(phys, phys)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def _draw_capsule(
    painter: QPainter,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    remaining: Optional[float],
    fill: QColor,
    dim: float = 1.0,
) -> None:
    """Track + remaining fill. Transparent outside the capsules (no tile)."""
    radius = h / 2.0
    track = QColor("#3b4261")
    track.setAlphaF(0.85 * dim)
    rect = QRectF(x, y, w, h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    painter.drawRoundedRect(rect, radius, radius)

    if remaining is None:
        return
    rem = _clamp(remaining) / 100.0
    fill_w = w * rem
    if fill_w < 0.75:
        return
    solid = QColor(fill)
    solid.setAlphaF(max(0.0, min(1.0, dim)))
    painter.setBrush(solid)
    painter.setClipRect(QRectF(x, y, fill_w, h))
    painter.drawRoundedRect(rect, radius, radius)
    painter.setClipping(False)


def _fill_value(remaining: Optional[float], show_as: str) -> Optional[float]:
    """Icon capsule length: remaining (default) or used (official toggle)."""
    if remaining is None:
        return None
    rem = _clamp(float(remaining))
    if show_as == "used":
        return 100.0 - rem
    return rem


def _fill_color(remaining: Optional[float], show_as: str, fallback: QColor) -> QColor:
    if remaining is None:
        return fallback
    rem = _clamp(float(remaining))
    if show_as == "used":
        return QColor(get_color_for_percent(100.0 - rem))
    return QColor(get_color_for_remaining(rem))


def paint_dual_window_pixmap(
    primary_remaining: Optional[float] = None,
    secondary_remaining: Optional[float] = None,
    size: int = DEFAULT_TRAY_SIZE,
    *,
    credits_remaining: Optional[float] = None,
    stale: bool = False,
    error: bool = False,
    show_percent: bool = False,  # unused; kept for API compat — never draw digits
    show_as: str = "remaining",
    icon_style: str = "dual_bars",
) -> QPixmap:
    """Official dual-bar meter only (no side digits, no dark tile)."""
    del show_percent
    size = max(16, int(size))
    pixmap, painter = _new_canvas(size)
    dim = 0.5 if stale else 1.0

    # Scale official 36px layout into our size with extra pad for Plasma crop.
    bar_w = size * 0.78
    bar_x = (size - bar_w) / 2.0

    top_h = size * (12.0 / 36.0) * 0.92
    bot_h = size * (8.0 / 36.0) * 0.92
    gap = size * (6.0 / 36.0) * 0.7
    stack = top_h + gap + bot_h
    top_y = (size - stack) / 2.0
    bot_y = top_y + top_h + gap

    base = QColor("#c0caf5")
    if error:
        base = QColor("#f7768e")

    has_weekly = secondary_remaining is not None and icon_style != "primary_only"
    weekly_ok = has_weekly and (secondary_remaining or 0) > 0
    credits_ratio: Optional[float] = None
    if credits_remaining is not None:
        credits_ratio = min(
            100.0, max(0.0, float(credits_remaining) / CREDITS_CAP * 100.0)
        )

    # Top = session (or credits if weekly exhausted)
    top_rem = primary_remaining
    top_fill = _fill_color(top_rem, show_as, base)
    if has_weekly and not weekly_ok and credits_ratio and credits_ratio > 0:
        top_rem = credits_ratio
        top_fill = QColor("#7aa2f7")
    if error:
        top_rem = None
        top_fill = base

    # Brand+percent mode: solid letter-like glyph via short dual stub + thick top
    if icon_style == "brand_percent":
        # Single centered capsule only
        mid_h = size * 0.28
        mid_y = (size - mid_h) / 2.0
        _draw_capsule(
            painter,
            x=bar_x,
            y=mid_y,
            w=bar_w,
            h=mid_h,
            remaining=_fill_value(top_rem, show_as),
            fill=top_fill,
            dim=dim,
        )
        painter.end()
        return pixmap

    _draw_capsule(
        painter,
        x=bar_x,
        y=top_y if icon_style != "primary_only" else (size - top_h * 1.2) / 2.0,
        w=bar_w,
        h=top_h * (1.2 if icon_style == "primary_only" else 1.0),
        remaining=_fill_value(top_rem, show_as),
        fill=top_fill,
        dim=dim,
    )

    if icon_style == "primary_only":
        painter.end()
        return pixmap

    # Bottom = weekly
    if weekly_ok:
        _draw_capsule(
            painter,
            x=bar_x,
            y=bot_y,
            w=bar_w,
            h=bot_h,
            remaining=_fill_value(secondary_remaining, show_as),
            fill=_fill_color(secondary_remaining, show_as, base),
            dim=dim,
        )
    else:
        _draw_capsule(
            painter,
            x=bar_x,
            y=bot_y,
            w=bar_w,
            h=bot_h,
            remaining=0.0 if has_weekly else None,
            fill=_fill_color(0.0, show_as, base) if has_weekly else base,
            dim=0.45 * dim,
        )

    painter.end()
    return pixmap


def paint_usage_pixmap(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = DEFAULT_TRAY_SIZE,
    *,
    remaining: Optional[float] = None,
    primary_remaining: Optional[float] = None,
    secondary_remaining: Optional[float] = None,
    credits_remaining: Optional[float] = None,
    stale: bool = False,
    show_percent: bool = False,
    show_as: str = "remaining",
    icon_style: str = "dual_bars",
) -> QPixmap:
    """Tray entry point — dual bars (or primary-only / brand)."""
    del show_percent
    if remaining is None and percent is not None:
        remaining = 100.0 - _clamp(percent)

    if primary_remaining is not None or secondary_remaining is not None:
        return paint_dual_window_pixmap(
            primary_remaining=primary_remaining
            if primary_remaining is not None
            else remaining,
            secondary_remaining=secondary_remaining,
            size=size,
            credits_remaining=credits_remaining,
            stale=stale,
            error=error,
            show_as=show_as,
            icon_style=icon_style,
        )

    if remaining is not None or error:
        return paint_dual_window_pixmap(
            primary_remaining=remaining,
            secondary_remaining=None,
            size=size,
            credits_remaining=credits_remaining,
            stale=stale,
            error=error,
            show_as=show_as,
            icon_style=icon_style,
        )

    return paint_dual_window_pixmap(
        primary_remaining=None,
        secondary_remaining=None,
        size=size,
        stale=True,
        error=False,
        show_as=show_as,
        icon_style=icon_style,
    )


def svg_to_qicon_pixmap(svg_string: str) -> QPixmap:
    del svg_string
    return paint_usage_pixmap(remaining=None)


def make_simple_pixmap(
    text: str, size: int = DEFAULT_TRAY_SIZE, color: str = "#89b4fa"
) -> QPixmap:
    """Loading: empty dual tracks."""
    del text, color
    return paint_dual_window_pixmap(
        primary_remaining=None,
        secondary_remaining=None,
        size=size,
        stale=True,
    )
