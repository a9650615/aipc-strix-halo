"""Tray icon — dual remaining bars + % (official CodexBar meter, Linux-safe).

Geometry based on steipete/CodexBar ``IconRenderer.swift`` (session top + weekly
bottom capsules, fill = remaining). Plasma/KDE clips edge-to-edge icons, so we
use a **safe inset** and a compact dual-bar column with a **percent label**
(menu-bar display mode "both": bars + %).
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QPixmap

logger = logging.getLogger("codexbar_gui.icon_updater")

# Plasma tray slots are small; keep logical size modest and pad content hard.
DEFAULT_TRAY_SIZE = 22
CREDITS_CAP = 1000.0


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _device_pixel_ratio() -> float:
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    return max(1.0, float(screen.devicePixelRatio()))


def get_color_for_percent(percent: float) -> str:
    """Color by *used* percent (high used = bad)."""
    clamped = _clamp(percent)
    if clamped > 80:
        return "#e74c3c"
    if clamped > 50:
        return "#f39c12"
    return "#27ae60"


def get_color_for_remaining(remaining: float) -> str:
    """Color by *remaining* percent (low left = bad)."""
    r = _clamp(remaining)
    if r <= 20:
        return "#f38ba8"
    if r <= 50:
        return "#fab387"
    return "#cdd6f4"


def generate_svg(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = 24,
) -> str:
    del size
    if error:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">'
            '<rect x="2" y="4" width="10" height="5" rx="2.5" fill="#45475a"/>'
            '<rect x="2" y="11" width="10" height="3" rx="1.5" fill="#45475a"/>'
            '<text x="17" y="14" text-anchor="middle" font-size="8" fill="#f38ba8">!</text></svg>'
        )
    used = 0.0 if percent is None else _clamp(percent)
    rem = int(round(100.0 - used))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">'
        f'<rect x="1" y="5" width="11" height="5" rx="2.5" fill="#45475a"/>'
        f'<rect x="1" y="12" width="11" height="3" rx="1.5" fill="#45475a"/>'
        f'<text x="17" y="14" text-anchor="middle" font-size="8" '
        f'font-family="sans-serif" font-weight="700" fill="#cdd6f4">{rem}</text></svg>'
    )


def svg_to_qicon_data(svg_string: str) -> str:
    import urllib.parse

    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg_string, safe="")


def _new_canvas(size: int) -> tuple[QPixmap, QPainter]:
    """HiDPI canvas: paint in *logical* coords 0..size (do not double-scale)."""
    dpr = max(1.0, _device_pixel_ratio())
    # Prefer ≥2× for Plasma downscale sharpness without exceeding huge bitmaps.
    dpr = max(dpr, 2.0)
    phys = max(1, int(round(size * dpr)))
    pixmap = QPixmap(phys, phys)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    # No painter.scale — setDevicePixelRatio already maps logical→physical.
    return pixmap, painter


def _draw_capsule_bar(
    painter: QPainter,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    remaining: Optional[float],
    fill: QColor,
    track_alpha: float = 0.32,
    dim: float = 1.0,
) -> None:
    """Capsule meter; fill = remaining, left→right. Thin stroke to avoid clip bloom."""
    radius = h / 2.0
    track = QColor("#45475a")
    track.setAlphaF(max(0.0, min(1.0, track_alpha * dim)))
    rect = QRectF(x, y, w, h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    painter.drawRoundedRect(rect, radius, radius)

    if remaining is None:
        return
    rem = _clamp(remaining) / 100.0
    fill_w = w * rem
    if fill_w <= 0.5:
        return
    solid = QColor(fill)
    solid.setAlphaF(max(0.0, min(1.0, dim)))
    painter.setBrush(solid)
    # Straight right edge (official): clip capsule, paint left rect
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
    show_percent: bool = True,
) -> QPixmap:
    """Dual bars (session/weekly) + optional remaining % — safe for KDE tray crop.

    Layout (logical size S)::

        | pad |  dual bars (compact)  |  %  | pad |
              top = session (thicker)
              bot = weekly (thinner)
    """
    size = max(16, int(size))
    pixmap, painter = _new_canvas(size)

    # Hard pad so Plasma status-notifier never clips the capsule edges.
    pad = max(1.5, size * 0.12)
    inner = size - 2.0 * pad
    dim = 0.55 if stale else 1.0

    # Headline remaining for % label (session first, else weekly, else worst)
    headline: Optional[float] = None
    if primary_remaining is not None:
        headline = primary_remaining
    elif secondary_remaining is not None:
        headline = secondary_remaining

    # Split horizontal: bars left, percent right
    pct_w = 0.0
    if show_percent and not error:
        # Reserve room for 1–3 digits
        pct_w = max(size * 0.36, 7.0)
    bars_w = inner - pct_w
    if pct_w > 0:
        bars_w = max(size * 0.42, bars_w - 0.5)

    # Vertical: two bars stacked with gap, centered in remaining height
    # Thinner than 1:1 IconRenderer scale so they don't dominate/clip.
    top_h = max(2.5, size * 0.18)
    bot_h = max(1.8, size * 0.11)
    gap = max(1.2, size * 0.07)
    stack_h = top_h + gap + bot_h
    top_y = pad + max(0.0, (inner - stack_h) / 2.0)
    bot_y = top_y + top_h + gap
    bar_x = pad
    bar_w = bars_w

    base = QColor("#cdd6f4")
    if error:
        base = QColor("#f38ba8")

    has_weekly = secondary_remaining is not None
    weekly_available = has_weekly and (secondary_remaining or 0) > 0
    credits_ratio: Optional[float] = None
    if credits_remaining is not None:
        credits_ratio = min(
            100.0, max(0.0, float(credits_remaining) / CREDITS_CAP * 100.0)
        )

    if error:
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=top_y,
            w=bar_w,
            h=top_h,
            remaining=None,
            fill=base,
            dim=dim,
        )
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=bot_y,
            w=bar_w,
            h=bot_h,
            remaining=None,
            fill=base,
            dim=0.45 * dim,
        )
        painter.setPen(QColor("#f38ba8"))
        font = QFont("Sans")
        font.setBold(True)
        font.setPixelSize(max(8, int(size * 0.42)))
        painter.setFont(font)
        painter.drawText(
            QRectF(pad + bars_w, pad, pct_w if pct_w else inner, inner),
            int(Qt.AlignmentFlag.AlignCenter),
            "!",
        )
        painter.end()
        return pixmap

    # Top lane
    if weekly_available or has_weekly or primary_remaining is not None:
        top_rem = primary_remaining
        top_fill = (
            base
            if top_rem is None
            else QColor(get_color_for_remaining(top_rem))
        )
        # Credits override when weekly exhausted and credits available
        if has_weekly and not weekly_available and credits_ratio and credits_ratio > 0:
            top_rem = credits_ratio
            top_fill = QColor("#89b4fa")
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=top_y,
            w=bar_w,
            h=top_h,
            remaining=top_rem,
            fill=top_fill,
            dim=dim,
        )
    else:
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=top_y,
            w=bar_w,
            h=top_h,
            remaining=None,
            fill=base,
            dim=0.5 * dim,
        )

    # Bottom lane
    if weekly_available:
        bot_fill = QColor(get_color_for_remaining(secondary_remaining or 0.0))
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=bot_y,
            w=bar_w,
            h=bot_h,
            remaining=secondary_remaining,
            fill=bot_fill,
            dim=dim,
        )
    else:
        # Dim empty weekly track (N/A) — thinner visual weight
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=bot_y,
            w=bar_w,
            h=bot_h,
            remaining=0.0 if has_weekly else None,
            fill=QColor(get_color_for_remaining(0.0)) if has_weekly else base,
            dim=0.4 * dim,
        )

    # Percent indicator (primary/session remaining, official "both" display mode)
    if show_percent and headline is not None:
        label = str(int(round(_clamp(headline))))
        color = QColor(get_color_for_remaining(headline))
        painter.setPen(color)
        font = QFont("Sans")
        font.setBold(True)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        # Fit 1–3 digits in the right column
        max_px = max(7, int(size * (0.42 if len(label) < 3 else 0.34)))
        font.setPixelSize(max_px)
        # Shrink until it fits
        fm = QFontMetrics(font)
        while font.pixelSize() > 6 and fm.horizontalAdvance(label) > pct_w - 0.5:
            font.setPixelSize(font.pixelSize() - 1)
            fm = QFontMetrics(font)
        painter.setFont(font)
        text_rect = QRectF(pad + bars_w, pad, pct_w, inner)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter),
            label,
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
    show_percent: bool = True,
) -> QPixmap:
    """Tray entry — dual bars + % (safe insets for system tray)."""
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
            show_percent=show_percent,
        )

    if remaining is not None or error:
        return paint_dual_window_pixmap(
            primary_remaining=remaining,
            secondary_remaining=None,
            size=size,
            credits_remaining=credits_remaining,
            stale=stale,
            error=error,
            show_percent=show_percent,
        )

    return paint_dual_window_pixmap(
        primary_remaining=None,
        secondary_remaining=None,
        size=size,
        stale=True,
        error=False,
        show_percent=False,
    )


def svg_to_qicon_pixmap(svg_string: str) -> QPixmap:
    del svg_string
    return paint_usage_pixmap(remaining=None)


def make_simple_pixmap(
    text: str, size: int = DEFAULT_TRAY_SIZE, color: str = "#89b4fa"
) -> QPixmap:
    """Loading placeholder: empty dual bars, no digit."""
    return paint_dual_window_pixmap(
        primary_remaining=None,
        secondary_remaining=None,
        size=size,
        stale=True,
        show_percent=False,
    )
