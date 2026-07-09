"""Tray / row icons for CodexBar GUI.

Prefer a painted QPixmap (always works). Optional SVG string helpers remain
for tests and theme tooling.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap, QPen, QFont

logger = logging.getLogger("codexbar_gui.icon_updater")


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def get_color_for_percent(percent: float) -> str:
    clamped = _clamp(percent)
    if clamped > 80:
        return "#e74c3c"
    if clamped > 50:
        return "#f39c12"
    return "#27ae60"


def generate_svg(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = 24,
) -> str:
    """SVG markup (for tests / optional renderers)."""
    del size
    if percent is not None:
        percent = _clamp(percent)
    if error:
        color, bg, fill_width, error_dot = "#e74c3c", "#2c3e50", 20.0, (
            '<circle cx="18" cy="6" r="3" fill="#e74c3c" stroke="white" stroke-width="1"/>'
        )
    elif percent is None:
        color, bg, fill_width, error_dot = "#95a5a6", "#34495e", 0.0, ""
    else:
        color = get_color_for_percent(percent)
        bg, fill_width, error_dot = "#2c3e50", max(0.0, (percent / 100.0) * 20.0), ""
    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <rect x="1" y="1" width="22" height="22" rx="3" ry="3"
        fill="{bg}" stroke="#555" stroke-width="0.5"/>
  <rect x="2" y="10" width="{fill_width:.1f}" height="4" rx="1" ry="1"
        fill="{color}" opacity="0.9"/>
  {error_dot}
</svg>
"""


def svg_to_qicon_data(svg_string: str) -> str:
    import urllib.parse

    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg_string, safe="")


def paint_usage_pixmap(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = 24,
) -> QPixmap:
    """Paint a meter icon — reliable on Plasma / StatusNotifier."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if error:
        fill = QColor("#e74c3c")
        bg = QColor("#2c3e50")
        bar_frac = 1.0
    elif percent is None:
        fill = QColor("#95a5a6")
        bg = QColor("#34495e")
        bar_frac = 0.0
    else:
        p = _clamp(percent)
        fill = QColor(get_color_for_percent(p))
        bg = QColor("#2c3e50")
        bar_frac = p / 100.0

    margin = 1.0
    outer = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.setPen(QPen(QColor("#555555"), 0.8))
    painter.setBrush(bg)
    painter.drawRoundedRect(outer, 4, 4)

    if bar_frac > 0:
        bar_h = max(3.0, size * 0.18)
        bar_y = (size - bar_h) / 2.0
        bar_w = max(0.0, (size - 6.0) * bar_frac)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(3.0, bar_y, bar_w, bar_h), 1.5, 1.5)

    if error:
        painter.setBrush(QColor("#e74c3c"))
        painter.setPen(QPen(QColor("#ffffff"), 1.0))
        painter.drawEllipse(QRectF(size - 9, 2, 6, 6))

    painter.end()
    return pixmap


def svg_to_qicon_pixmap(svg_string: str) -> QPixmap:
    """Best-effort SVG → pixmap; fall back to painted meter."""
    del svg_string
    return paint_usage_pixmap()


def make_simple_pixmap(text: str, size: int = 24, color: str = "#4a90d9") -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 4, 4)
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setPointSizeF(size * 0.45)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, (text or "C")[:1].upper())
    painter.end()
    return pixmap
