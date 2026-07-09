"""Embedded icons for CodexBar — no external icon files needed."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont

logger = logging.getLogger("codexbar_gui.icons")


def _make_pixmap(text: str, size: int, color: str = "#4a90d9") -> QPixmap:
    """Render a colored square with centered text as a QPixmap."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.TranslucentColor)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rect = pixmap.rect().adjusted(1, 1, -1, -1)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(rect, 4, 4)

    painter.setPen(QColor("#ffffff"))
    font = QFont("Sans", int(size * 0.5))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignCenter, text[:1].upper())
    painter.end()
    return pixmap


# Pre-rendered tray icon (CodexBar logo — a stylized "C").
def get_tray_icon() -> QIcon:
    return QIcon(_make_pixmap("C", 128, "#4a90d9"))


# Per-provider icon shortcuts. Falls back to the default tray icon.
_PROVIDER_COLORS: dict[str, str] = {
    "codex": "#00d4aa",
    "openai": "#10a37f",
    "claude": "#d97706",
    "gemini": "#8e7cc3",
    "copilot": "#0e68de",
    "cursor": "#ff0080",
    "windsurf": "#00bcd4",
    "zed": "#f5c542",
}


def get_provider_icons() -> dict[str, QIcon]:
    icons: dict[str, QIcon] = {}
    for pid, color in _PROVIDER_COLORS.items():
        icons[pid] = QIcon(_make_pixmap(pid[:2], 64, color))
    return icons


def get_provider_color(provider_id: str) -> str:
    """Return the accent color for a provider, or the default blue."""
    return _PROVIDER_COLORS.get(provider_id.lower(), "#4a90d9")
