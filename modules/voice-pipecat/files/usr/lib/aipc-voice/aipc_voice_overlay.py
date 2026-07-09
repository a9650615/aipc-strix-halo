#!/usr/bin/env python3
"""Siri-like partial screen overlay for AIPC voice state.

Watches $XDG_RUNTIME_DIR/aipc-voice-state.json (written by aipc_voice_ux) and
shows a translucent always-on-top panel: orb + status + detail/transcript.

Not a full-screen modal — edges stay visible (partial overlay), Esc dismisses
the panel only (does not kill the voice pipeline).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QPoint,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# Any voice activity → show overlay (incl. detecting / miss feedback)
# Only intentional assistant turns — NOT ambient energy "detecting"/"miss" spam
SHOW_STATES = frozenset(
    {
        "wake",
        "recording",
        "thinking",
        "speaking",
        "no_speech",
        "error",
    }
)
HIDE_STATES = frozenset({"listening", "done", "muted", "miss", "detecting"})

STATE_COLORS = {
    "listening": QColor(120, 140, 180),
    "wake": QColor(90, 200, 255),
    "recording": QColor(80, 220, 160),
    "thinking": QColor(180, 140, 255),
    "speaking": QColor(100, 180, 255),
    "done": QColor(140, 140, 150),
    "no_speech": QColor(255, 180, 80),
    "error": QColor(255, 90, 90),
    "miss": QColor(160, 160, 160),
    "muted": QColor(100, 100, 110),
    "detecting": QColor(255, 200, 80),
}

STATE_HINTS = {
    "listening": "說「嘿助理」或按控制中心",
    "wake": "請說指令，說完停一下",
    "recording": "正在聽你說話…",
    "thinking": "思考中…",
    "speaking": "回答中",
    "done": "待命",
    "no_speech": "沒聽到，請再說一次",
    "error": "出錯了",
    "muted": "已靜音",
    "detecting": "辨識喚醒詞中…",
    "miss": "聽到了，但不是喚醒詞",
}


def status_path() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "aipc-voice-state.json"
    return Path.home() / ".cache/aipc/voice-state.json"


def read_status() -> dict:
    p = status_path()
    if not p.is_file():
        return {"state": "listening", "detail": "", "label": "AIPC · 監聽中"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "listening", "detail": "", "label": ""}


class OrbWidget(QWidget):
    """Pulsing orb — visual anchor like Siri waveform ball."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self._phase = 0.0
        self._color = STATE_COLORS["listening"]
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str, active: bool) -> None:
        self._color = STATE_COLORS.get(state, STATE_COLORS["listening"])
        self._active = active
        self.update()

    def _tick(self) -> None:
        if self._active:
            self._phase += 0.12
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        base = 14.0
        pulse = (4.0 * (0.5 + 0.5 * math.sin(self._phase))) if self._active else 0.0
        r = base + pulse

        # soft outer glow
        for i, alpha in ((1.8, 30), (1.4, 55), (1.0, 200)):
            grad = QRadialGradient(cx, cy, r * i)
            c = QColor(self._color)
            c.setAlpha(alpha)
            grad.setColorAt(0.0, c)
            c2 = QColor(self._color)
            c2.setAlpha(0)
            grad.setColorAt(1.0, c2)
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r * i), int(r * i))

        # core
        core = QColor(255, 255, 255, 230 if self._active else 160)
        p.setBrush(core)
        p.setPen(QPen(self._color, 1.5))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(base * 0.45), int(base * 0.45))
        p.end()


class OverlayPanel(QWidget):
    """Fixed top-right HUD — never steals focus or keyboard from other apps."""

    dismissed = Signal()

    def __init__(self):
        # Tool + DoesNotAcceptFocus + ShowWithoutActivating = overlay, not a "window"
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("AIPC Voice")

        self._state = "listening"
        self._detail = ""
        self._label = ""
        self._hide_at: float | None = None
        self._pinned_xy: tuple[int, int] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(3)
        root.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.orb = OrbWidget()
        root.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignHCenter)

        self.title = QLabel("AIPC")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet("color: #f2f4f8;")
        root.addWidget(self.title)

        self.hint = QLabel("")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hint.setStyleSheet("color: #c5cdd8; font-size: 9px;")
        root.addWidget(self.hint)

        self.detail = QLabel("")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.detail.setStyleSheet("color: #9aa6b5; font-size: 9px;")
        self.detail.setMinimumWidth(140)
        self.detail.setMaximumWidth(200)
        root.addWidget(self.detail)

        self.foot = QLabel("右上角 · 不搶焦點")
        self.foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.foot.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.foot.setStyleSheet("color: #6a7380; font-size: 8px;")
        root.addWidget(self.foot)

        self.setFixedWidth(180)
        self.adjustSize()

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start(200)

        # Re-pin to top-right if geometry/size changes (multi-monitor safe)
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._place)
        self._pos_timer.start(2000)

        self.hide()
        self._on_poll()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        # glass card
        bg = QColor(18, 22, 30, 210)
        p.fillPath(path, bg)
        pen = QPen(QColor(255, 255, 255, 35))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        # top sheen
        sheen = QColor(255, 255, 255, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(sheen)
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -rect.height() * 0.55), 14, 14)
        p.end()

    def _show_passive(self) -> None:
        """Show without activating / raising as a real window (no focus steal)."""
        self._place()
        # show() + ShowWithoutActivating — never activateWindow / raise_
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()

    def _place(self) -> None:
        """Pin to top-right of primary availableGeometry (fixed corner HUD)."""
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        # Prefer availableGeometry (excludes panels); fall back to full geometry
        geo = screen.availableGeometry()
        self.adjustSize()
        w, h = self.width(), self.height()
        margin = 12
        x = int(geo.right() - w - margin)
        y = int(geo.top() + margin)
        # setGeometry is more reliable than move() on some WMs
        self.setGeometry(x, y, w, h)
        wh = self.windowHandle()
        if wh is not None:
            try:
                wh.setPosition(x, y)
            except Exception:
                pass
        self._pinned_xy = (x, y)

    def apply_status(self, data: dict) -> None:
        state = str(data.get("state") or "listening")
        detail = str(data.get("detail") or "")
        partial = str(data.get("partial") or data.get("hint") or "")
        label = str(data.get("label") or "")
        self._state = state
        self._detail = detail or partial
        self._label = label

        active = state in SHOW_STATES
        self.orb.set_state(state, active=active and state != "error")

        self.title.setText(label or f"AIPC · {state}")
        self.hint.setText(STATE_HINTS.get(state, ""))
        shown = partial or detail
        if shown and shown not in ("…",):
            d = shown if len(shown) <= 56 else shown[:53] + "…"
            self.detail.setText(d)
            self.detail.show()
        else:
            self.detail.setText("")
            self.detail.hide()

        self.adjustSize()

        if state in SHOW_STATES:
            self._show_passive()
            if state in ("detecting", "miss", "no_speech"):
                self._hide_at = time.time() + (2.8 if state == "miss" else 2.0)
            else:
                self._hide_at = None
        elif state in HIDE_STATES:
            if state == "done" and self.isVisible():
                self._hide_at = time.time() + 1.2
            elif state == "listening":
                self._hide_at = time.time() + 0.3
            elif state == "muted":
                self._hide_at = time.time() + 1.0
            else:
                self._hide_at = time.time() + 0.5
            self._place()
        else:
            self._place()

    def _on_poll(self) -> None:
        data = read_status()
        # only re-apply when changed enough
        key = (data.get("state"), data.get("detail"), data.get("label"), data.get("ts"))
        if getattr(self, "_last_key", None) != key:
            self._last_key = key
            self.apply_status(data)
        if self._hide_at is not None and time.time() >= self._hide_at:
            self.hide()
            self._hide_at = None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # HiDPI
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    # Wayland ignores QWidget.move() for Tool windows → appear centered.
    # Prefer XWayland (xcb) so top-right pin works under KDE Wayland.
    if os.environ.get("AIPC_OVERLAY_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = os.environ["AIPC_OVERLAY_PLATFORM"]
    elif os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QApplication(argv)
    app.setApplicationName("aipc-voice-overlay")
    app.setQuitOnLastWindowClosed(False)

    panel = OverlayPanel()
    # keep process alive
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
