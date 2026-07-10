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


def paint_dual_window_pixmap(
    primary_remaining: Optional[float] = None,
    secondary_remaining: Optional[float] = None,
    size: int = DEFAULT_TRAY_SIZE,
    *,
    credits_remaining: Optional[float] = None,
    stale: bool = False,
    error: bool = False,
    show_percent: bool = False,  # unused; kept for API compat — never draw digits
) -> QPixmap:
    """Official dual-bar meter only (no side digits, no dark tile)."""
    del show_percent
    size = max(16, int(size))
    pixmap, painter = _new_canvas(size)
    dim = 0.5 if stale else 1.0

    # Scale official 36px layout into our size with extra pad for Plasma crop.
    # Official: barW=30, top y=5 h=12, bot y=23 h=8 (Qt coords from AppKit flip)
    pad = max(2.0, size * 0.14)
    # Usable box
    box = size - 2.0 * pad
    # Horizontal: almost full width of usable box (official ~30/36)
    bar_w = box * (30.0 / 36.0) / (30.0 / 36.0) * (box * 0.92)
    # simplify: bar_w = 0.78 * size centered
    bar_w = size * 0.78
    bar_x = (size - bar_w) / 2.0

    # Vertical: match official ratio of gaps
    # top h : bot h ≈ 12 : 8, with margins
    top_h = size * (12.0 / 36.0) * 0.92  # slightly tighter
    bot_h = size * (8.0 / 36.0) * 0.92
    gap = size * (6.0 / 36.0) * 0.7
    stack = top_h + gap + bot_h
    top_y = (size - stack) / 2.0
    bot_y = top_y + top_h + gap

    base = QColor("#c0caf5")
    if error:
        base = QColor("#f7768e")

    has_weekly = secondary_remaining is not None
    weekly_ok = has_weekly and (secondary_remaining or 0) > 0
    credits_ratio: Optional[float] = None
    if credits_remaining is not None:
        credits_ratio = min(
            100.0, max(0.0, float(credits_remaining) / CREDITS_CAP * 100.0)
        )

    # Top = session (or credits if weekly exhausted)
    top_rem = primary_remaining
    top_fill = base if top_rem is None else QColor(get_color_for_remaining(top_rem))
    if has_weekly and not weekly_ok and credits_ratio and credits_ratio > 0:
        top_rem = credits_ratio
        top_fill = QColor("#7aa2f7")
    if error:
        top_rem = None
        top_fill = base

    _draw_capsule(
        painter,
        x=bar_x,
        y=top_y,
        w=bar_w,
        h=top_h,
        remaining=top_rem,
        fill=top_fill,
        dim=dim,
    )

    # Bottom = weekly
    if weekly_ok:
        _draw_capsule(
            painter,
            x=bar_x,
            y=bot_y,
            w=bar_w,
            h=bot_h,
            remaining=secondary_remaining,
            fill=QColor(get_color_for_remaining(secondary_remaining or 0)),
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
            fill=QColor(get_color_for_remaining(0.0)) if has_weekly else base,
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
) -> QPixmap:
    """Tray entry point — dual bars only."""
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
        )

    if remaining is not None or error:
        return paint_dual_window_pixmap(
            primary_remaining=remaining,
            secondary_remaining=None,
            size=size,
            credits_remaining=credits_remaining,
            stale=stale,
            error=error,
        )

    return paint_dual_window_pixmap(
        primary_remaining=None,
        secondary_remaining=None,
        size=size,
        stale=True,
        error=False,
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
