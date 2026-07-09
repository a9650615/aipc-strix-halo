"""Tray icon: meter + remaining percent digits (menu-bar style headline)."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

logger = logging.getLogger("codexbar_gui.icon_updater")


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


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
        return "#e74c3c"
    if r <= 50:
        return "#f39c12"
    return "#a6e3a1"


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
    color = get_color_for_remaining(rem)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
        f'<rect width="24" height="24" rx="4" fill="#1e1e2e"/>'
        f'<text x="12" y="16" text-anchor="middle" font-size="9" '
        f'font-family="sans-serif" font-weight="700" fill="{color}">'
        f"{int(rem)}</text></svg>"
    )


def svg_to_qicon_data(svg_string: str) -> str:
    import urllib.parse

    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg_string, safe="")


def paint_usage_pixmap(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = 24,
    *,
    remaining: Optional[float] = None,
) -> QPixmap:
    """Paint tray icon.

    ``percent`` is *used* 0–100 (legacy). Prefer ``remaining`` when known.
    Icon shows **remaining** integer like macOS menu-bar label.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if remaining is None and percent is not None:
        remaining = 100.0 - _clamp(percent)

    bg = QColor("#1e1e2e")
    if error:
        fill = QColor("#e74c3c")
        label = "!"
    elif remaining is None:
        fill = QColor("#6c7086")
        label = "—"
    else:
        rem = _clamp(remaining)
        fill = QColor(get_color_for_remaining(rem))
        label = str(int(round(rem)))

    margin = 1.0
    outer = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.setPen(QPen(QColor("#45475a"), 1.0))
    painter.setBrush(bg)
    painter.drawRoundedRect(outer, 5, 5)

    # Bottom remaining bar
    if remaining is not None and not error:
        bar_h = max(3.0, size * 0.14)
        bar_y = size - bar_h - 2.5
        bar_w = max(0.0, (size - 6.0) * (_clamp(remaining) / 100.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#313244"))
        painter.drawRoundedRect(QRectF(3.0, bar_y, size - 6.0, bar_h), 1.5, 1.5)
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(3.0, bar_y, bar_w, bar_h), 1.5, 1.5)

    painter.setPen(fill)
    font = QFont("Sans")
    font.setBold(True)
    # Fit 1–3 digits
    font.setPixelSize(max(9, int(size * (0.42 if len(label) < 3 else 0.34))))
    painter.setFont(font)
    text_rect = QRectF(0, 0, size, size - (4 if remaining is not None else 0))
    painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignCenter), label)

    painter.end()
    return pixmap


def svg_to_qicon_pixmap(svg_string: str) -> QPixmap:
    del svg_string
    return paint_usage_pixmap(remaining=None)


def make_simple_pixmap(text: str, size: int = 24, color: str = "#89b4fa") -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1e1e2e"))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 5, 5)
    painter.setPen(QColor(color))
    font = QFont("Sans")
    font.setBold(True)
    font.setPixelSize(int(size * 0.45))
    painter.setFont(font)
    painter.drawText(
        pixmap.rect(), Qt.AlignmentFlag.AlignCenter, (text or "C")[:1].upper()
    )
    painter.end()
    return pixmap
