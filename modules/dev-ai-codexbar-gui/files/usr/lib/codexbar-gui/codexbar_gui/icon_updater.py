"""Tray icon — dual remaining bars matching official CodexBar IconRenderer.

Upstream (steipete/CodexBar ``Sources/CodexBar/IconRenderer.swift``):

- 18×18 pt template, rendered at 2× → 36×36 px canvas
- bar width 30 px, centered
- top (session/primary): y=19,h=12 in AppKit bottom-up coords → upper capsule
- bottom (weekly/secondary): y=5,h=8 → lower thinner capsule
- fill = percent **remaining** left-to-right; straight fill edge inside capsule

When weekly is missing/exhausted and credits exist, official thickens the
credits lane (we mirror that when ``credits_remaining`` is provided).
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap

logger = logging.getLogger("codexbar_gui.icon_updater")

# Official output is 18pt; KDE trays are often ~22–32. We scale the 36px design.
OFFICIAL_CANVAS_PX = 36
DEFAULT_TRAY_SIZE = 24
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
    return "#cdd6f4"  # near monochrome/template on dark panels


def generate_svg(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = 24,
) -> str:
    del size
    if error:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
            '<rect width="24" height="24" rx="4" fill="#2c3e50"/>'
            '<circle cx="12" cy="12" r="5" fill="#e74c3c"/></svg>'
        )
    used = 0.0 if percent is None else _clamp(percent)
    rem = 100.0 - used
    # SVG dual-bar sketch (remaining fill)
    top_w = max(0, min(20, int(20 * rem / 100)))
    bot_w = max(0, min(20, int(20 * rem / 100)))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
        f'<rect x="2" y="5" width="20" height="7" rx="3.5" fill="#313244"/>'
        f'<rect x="2" y="5" width="{top_w}" height="7" rx="3.5" fill="#cdd6f4"/>'
        f'<rect x="2" y="14" width="20" height="5" rx="2.5" fill="#313244"/>'
        f'<rect x="2" y="14" width="{bot_w}" height="5" rx="2.5" fill="#a6adc8"/>'
        f"</svg>"
    )


def svg_to_qicon_data(svg_string: str) -> str:
    import urllib.parse

    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg_string, safe="")


def _new_canvas(size: int) -> tuple[QPixmap, QPainter, float]:
    dpr = _device_pixel_ratio()
    phys = max(size, int(round(size * dpr)))
    pixmap = QPixmap(phys, phys)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if dpr != 1.0 and size > 0:
        painter.scale(phys / size, phys / size)
    return pixmap, painter, dpr


def _draw_capsule_bar(
    painter: QPainter,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    remaining: Optional[float],
    fill: QColor,
    track_alpha: float = 0.28,
    stroke_alpha: float = 0.44,
    dim: float = 1.0,
) -> None:
    """One capsule like IconRenderer.drawBar — fill remaining left→right."""
    radius = h / 2.0
    track = QColor(fill)
    track.setAlphaF(max(0.0, min(1.0, track_alpha * dim)))
    stroke = QColor(fill)
    stroke.setAlphaF(max(0.0, min(1.0, stroke_alpha * dim)))

    rect = QRectF(x, y, w, h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    painter.drawRoundedRect(rect, radius, radius)

    # Stroke inset ~1px equivalent
    inset = max(0.5, h * 0.08)
    painter.setPen(QPen(stroke, max(0.8, h * 0.12)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(
        QRectF(x + inset, y + inset, w - 2 * inset, h - 2 * inset),
        max(0.0, radius - inset),
        max(0.0, radius - inset),
    )

    if remaining is None:
        return
    rem = _clamp(remaining) / 100.0
    fill_w = w * rem
    if fill_w <= 0.01:
        return
    painter.setPen(Qt.PenStyle.NoPen)
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
) -> QPixmap:
    """Official dual-bar tray icon (session top + weekly bottom).

    Geometry scaled from IconRenderer 36×36 px layout.
    """
    size = max(16, int(size))
    pixmap, painter, _ = _new_canvas(size)
    s = size / float(OFFICIAL_CANVAS_PX)  # scale factor from official px

    # Official: barWidthPx=30, barXPx centered on 36
    bar_w = 30.0 * s
    bar_x = (size - bar_w) / 2.0
    # AppKit y-up → Qt y-down:
    # topRect (y=19,h=12) → Qt y = 36-19-12 = 5
    # bottomRect (y=5,h=8) → Qt y = 36-5-8 = 23
    top_y, top_h = 5.0 * s, 12.0 * s
    bot_y, bot_h = 23.0 * s, 8.0 * s
    # Credits thicker lane (y=14,h=16 AppKit) → Qt y = 36-14-16 = 6
    cred_y, cred_h = 6.0 * s, 16.0 * s
    cred_bot_y, cred_bot_h = 26.0 * s, 6.0 * s

    base = QColor("#cdd6f4")
    if error:
        base = QColor("#f38ba8")
    dim = 0.55 if stale else 1.0
    track_a = 0.18 if stale else 0.28
    stroke_a = 0.28 if stale else 0.44

    has_weekly = secondary_remaining is not None
    weekly_available = has_weekly and (secondary_remaining or 0) > 0
    credits_ratio: Optional[float] = None
    if credits_remaining is not None:
        credits_ratio = min(100.0, max(0.0, float(credits_remaining) / CREDITS_CAP * 100.0))

    if error:
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=top_y,
            w=bar_w,
            h=top_h,
            remaining=None,
            fill=base,
            track_alpha=track_a,
            stroke_alpha=stroke_a,
            dim=dim,
        )
        painter.setPen(QColor("#f38ba8"))
        font = QFont("Sans")
        font.setBold(True)
        font.setPixelSize(max(9, int(size * 0.45)))
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), "!")
        painter.end()
        return pixmap

    if weekly_available:
        # Normal: top=primary session, bottom=weekly
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=top_y,
            w=bar_w,
            h=top_h,
            remaining=primary_remaining,
            fill=base if primary_remaining is None else QColor(get_color_for_remaining(primary_remaining)),
            track_alpha=track_a,
            stroke_alpha=stroke_a,
            dim=dim,
        )
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=bot_y,
            w=bar_w,
            h=bot_h,
            remaining=secondary_remaining,
            fill=base
            if secondary_remaining is None
            else QColor(get_color_for_remaining(secondary_remaining)),
            track_alpha=track_a,
            stroke_alpha=stroke_a,
            dim=dim,
        )
    elif not has_weekly:
        # Weekly missing: session top + dim empty bottom (or credits-only)
        if primary_remaining is None and credits_ratio is not None:
            _draw_capsule_bar(
                painter,
                x=bar_x,
                y=cred_y,
                w=bar_w,
                h=cred_h,
                remaining=credits_ratio,
                fill=QColor("#89b4fa"),
                track_alpha=track_a,
                stroke_alpha=stroke_a,
                dim=dim,
            )
            _draw_capsule_bar(
                painter,
                x=bar_x,
                y=cred_bot_y,
                w=bar_w,
                h=cred_bot_h,
                remaining=None,
                fill=base,
                track_alpha=track_a,
                stroke_alpha=stroke_a,
                dim=0.45 * dim,
            )
        else:
            _draw_capsule_bar(
                painter,
                x=bar_x,
                y=top_y,
                w=bar_w,
                h=top_h,
                remaining=primary_remaining,
                fill=base
                if primary_remaining is None
                else QColor(get_color_for_remaining(primary_remaining)),
                track_alpha=track_a,
                stroke_alpha=stroke_a,
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
                track_alpha=track_a,
                stroke_alpha=stroke_a,
                dim=0.45 * dim,
            )
    else:
        # Weekly exhausted (0 left): credits thick top if any, weekly 0 bottom
        if credits_ratio is not None and credits_ratio > 0:
            _draw_capsule_bar(
                painter,
                x=bar_x,
                y=cred_y,
                w=bar_w,
                h=cred_h,
                remaining=credits_ratio,
                fill=QColor("#89b4fa"),
                track_alpha=track_a,
                stroke_alpha=stroke_a,
                dim=dim,
            )
        else:
            _draw_capsule_bar(
                painter,
                x=bar_x,
                y=top_y,
                w=bar_w,
                h=top_h,
                remaining=primary_remaining,
                fill=base
                if primary_remaining is None
                else QColor(get_color_for_remaining(primary_remaining)),
                track_alpha=track_a,
                stroke_alpha=stroke_a,
                dim=dim,
            )
        _draw_capsule_bar(
            painter,
            x=bar_x,
            y=cred_bot_y,
            w=bar_w,
            h=cred_bot_h,
            remaining=0.0,
            fill=QColor(get_color_for_remaining(0.0)),
            track_alpha=track_a,
            stroke_alpha=stroke_a,
            dim=dim,
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
) -> QPixmap:
    """Tray icon entry point — prefers official dual bars when both windows known."""
    if remaining is None and percent is not None:
        remaining = 100.0 - _clamp(percent)

    # Prefer dual-bar path (official default menu-bar meter).
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

    # Single remaining → dual with empty dim weekly track (matches "weekly N/A")
    if remaining is not None or error:
        return paint_dual_window_pixmap(
            primary_remaining=remaining,
            secondary_remaining=None,
            size=size,
            credits_remaining=credits_remaining,
            stale=stale,
            error=error,
        )

    # Unknown: empty dual tracks
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
    """Fallback letter tile (loading / no data yet)."""
    pixmap, painter, _ = _new_canvas(size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1e1e2e"))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 6, 6)
    # Two empty capsules so loading still looks like the meter
    s = size / float(OFFICIAL_CANVAS_PX)
    bar_w = 30.0 * s
    bar_x = (size - bar_w) / 2.0
    base = QColor(color)
    _draw_capsule_bar(
        painter,
        x=bar_x,
        y=5.0 * s,
        w=bar_w,
        h=12.0 * s,
        remaining=None,
        fill=base,
        dim=0.7,
    )
    _draw_capsule_bar(
        painter,
        x=bar_x,
        y=23.0 * s,
        w=bar_w,
        h=8.0 * s,
        remaining=None,
        fill=base,
        dim=0.45,
    )
    painter.end()
    return pixmap
