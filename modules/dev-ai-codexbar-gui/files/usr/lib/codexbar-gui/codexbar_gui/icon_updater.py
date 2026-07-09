"""SVG icon generator for the CodexBar system tray.

Generates dynamic SVG icons that reflect usage levels:

- Green (<50%): healthy usage
- Yellow (50-80%): approaching limit
- Red (>80%): near or over limit
- Gray (no data/error): unavailable

The icon is a rounded rectangle with an inner progress bar, rendered as
inline SVG so it can be set directly on ``QSystemTrayIcon`` via
``QIcon.fromTheme()`` or a data URL.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtGui import QPixmap

logger = logging.getLogger("codexbar_gui.icon_updater")


# SVG template — a 24x24 rounded rect with an inner fill bar.
_ICON_SVG_TEMPLATE = """\
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <defs>
    <clipPath id="round"><rect width="24" height="24" rx="4" ry="4"/></clipPath>
  </defs>
  <g clip-path="url(#round)">
    <!-- background -->
    <rect x="1" y="1" width="22" height="22" rx="3" ry="3"
          fill="{bg}" stroke="{stroke}" stroke-width="0.5"/>
    <!-- progress bar -->
    <rect x="2" y="10" width="{fill_width}" height="4" rx="1" ry="1"
          fill="{color}" opacity="0.9"/>
    <!-- error indicator dot -->
    {error_dot}
  </g>
</svg>
"""

_ERROR_DOT = """\
    <!-- error indicator -->
    <circle cx="18" cy="6" r="3" fill="#e74c3c" stroke="white" stroke-width="1"/>
"""


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def get_color_for_percent(percent: float) -> str:
    """Return an SVG hex color based on usage percentage.

    - <50%: green (#27ae60)
    - 50-80%: yellow (#f39c12)
    - >80%: red (#e74c3c)
    """
    clamped = _clamp(percent)
    if clamped > 80:
        return "#e74c3c"
    elif clamped > 50:
        return "#f39c12"
    return "#27ae60"


def generate_svg(
    percent: Optional[float] = None,
    error: bool = False,
    size: int = 24,
) -> str:
    """Generate an SVG icon string.

    Args:
        percent: Usage percentage (0-100). None means unknown/gray.
        error: If True, show red error dot indicator.
        size: Icon size in pixels (only affects viewBox, SVG scales).

    Returns:
        SVG markup as a UTF-8 string.
    """
    if percent is not None:
        percent = _clamp(percent)

    if error:
        color = "#e74c3c"
        bg = "#2c3e50"
        stroke = "#555"
        fill_width = 20.0
        error_dot = _ERROR_DOT
    elif percent is None:
        color = "#95a5a6"
        bg = "#34495e"
        stroke = "#555"
        fill_width = 0.0
        error_dot = ""
    else:
        color = get_color_for_percent(percent)
        bg = "#2c3e50"
        stroke = "#555"
        fill_width = max(0.0, (percent / 100.0) * 20.0)
        error_dot = ""

    return _ICON_SVG_TEMPLATE.format(
        bg=bg,
        stroke=stroke,
        color=color,
        fill_width=f"{fill_width:.1f}",
        error_dot=error_dot,
    )


def svg_to_qicon_data(svg_string: str) -> str:
    """Encode SVG as a data URI suitable for QIcon.fromPixmap().

    Returns a ``data:image/svg+xml;utf8,...`` string.
    """
    import urllib.parse
    encoded = urllib.parse.quote(svg_string, safe="")
    return f"data:image/svg+xml;utf8,{encoded}"


def svg_to_qicon_pixmap(svg_string: str) -> QPixmap:
    """Convert SVG string to a QPixmap, returning empty pixmap on error."""
    data_uri = svg_to_qicon_data(svg_string)
    pixmap = QPixmap()
    try:
        encoded = data_uri.encode("utf-8")
        if not pixmap.loadFromData(encoded):
            logger.warning("Failed to load SVG into QPixmap")
    except RuntimeError:
        # QApplication not constructed yet — return empty pixmap
        logger.debug("QApplication not available for SVG conversion")
        pass
    except Exception as e:
        logger.warning("SVG to pixmap conversion error: %s", e)
    return pixmap


def make_simple_pixmap(text: str, size: int = 24, color: str = "#4a90d9") -> QPixmap:
    """Create a simple colored square pixmap as fallback for tray icon."""
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtCore import Qt

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 4, 4)
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPointSizeF(size * 0.5)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text[:1].upper())
    painter.end()
    return pixmap
