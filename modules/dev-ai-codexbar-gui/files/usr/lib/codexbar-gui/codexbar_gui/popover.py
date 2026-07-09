"""Wayland-safe usage popover (QWidget window, not QMenu.popup).

On Wayland, ``QMenu.popup()`` without a transient parent that has received
input fails with:
  qt.qpa.wayland: Failed to create grabbing popup...
Tray right-click context menus also often fail with custom QWidgetActions.
A tool-style window is reliable on Plasma/Wayland.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from codexbar_gui.icon_updater import paint_usage_pixmap
from codexbar_gui.upstream import (
    ProviderView,
    RateWindowView,
    fetch_usage_views,
    find_codexbar_binary,
)

logger = logging.getLogger("codexbar_gui.popover")


class _WindowRow(QWidget):
    def __init__(self, win: RateWindowView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        name = QLabel(win.label)
        name.setFixedWidth(96)
        name.setFont(QFont("Sans", 9))
        layout.addWidget(name)

        rem = win.remaining_percent
        if rem <= 20:
            color = "#e74c3c"
        elif rem <= 50:
            color = "#f39c12"
        else:
            color = "#27ae60"

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(rem))
        bar.setFixedHeight(14)
        bar.setMinimumWidth(140)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar::chunk {{ background:{color}; border-radius:3px; }}"
            f"QProgressBar {{ border:none; background:#2c3e50; border-radius:3px; }}"
        )
        layout.addWidget(bar, 1)

        pct = QLabel(f"{int(rem)}% left")
        pct.setFixedWidth(64)
        pct.setStyleSheet(f"color:{color}; font-size:12px;")
        layout.addWidget(pct)

        reset = QLabel(win.reset_description or "")
        reset.setStyleSheet("color:#aaa; font-size:11px;")
        reset.setMinimumWidth(80)
        layout.addWidget(reset)


class _ProviderCard(QFrame):
    def __init__(self, view: ProviderView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background:#1e1e2e; border:1px solid #313244; border-radius:8px; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        head = QHBoxLayout()
        rem = view.headline_remaining
        icon = QLabel()
        icon.setPixmap(
            paint_usage_pixmap(
                percent=(100.0 - rem) if rem is not None else None,
                error=not view.ok,
                size=28,
            )
        )
        head.addWidget(icon)
        title = QLabel(f"<b>{view.display_name}</b>")
        title.setFont(QFont("Sans", 12))
        title.setStyleSheet("color:#cdd6f4; border:none;")
        head.addWidget(title)
        if view.source:
            src = QLabel(view.source)
            src.setStyleSheet("color:#6c7086; border:none; font-size:11px;")
            head.addWidget(src)
        head.addStretch()
        root.addLayout(head)

        if view.error:
            err = QLabel(view.error)
            err.setWordWrap(True)
            err.setStyleSheet("color:#f38ba8; border:none; font-size:11px;")
            root.addWidget(err)
            return

        for win in (view.primary, view.secondary, view.tertiary):
            if win is not None:
                root.addWidget(_WindowRow(win))

        if view.pace_summary:
            pace = QLabel(view.pace_summary)
            pace.setWordWrap(True)
            pace.setStyleSheet("color:#94e2d5; border:none; font-size:11px;")
            root.addWidget(pace)

        meta = []
        if view.account:
            meta.append(view.account)
        if view.plan:
            meta.append(f"plan:{view.plan}")
        if view.credits_remaining is not None:
            meta.append(f"credits:{view.credits_remaining:g}")
        if meta:
            m = QLabel(" · ".join(meta))
            m.setStyleSheet("color:#a6adc8; border:none; font-size:11px;")
            root.addWidget(m)


class UsagePopover(QWidget):
    """Frameless tool window shown near the tray / cursor."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("CodexBarPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._host = host
        self._port = port
        self._views: List[ProviderView] = []

        self.setStyleSheet(
            "#CodexBarPopover { background:#11111b; border:1px solid #45475a; border-radius:10px; }"
            "QLabel { color:#cdd6f4; }"
            "QPushButton { background:#313244; color:#cdd6f4; border:none; "
            "padding:6px 12px; border-radius:6px; }"
            "QPushButton:hover { background:#45475a; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("<b>CodexBar</b>")
        title.setFont(QFont("Sans", 13))
        title_row.addWidget(title)
        title_row.addStretch()
        self._status = QLabel("")
        self._status.setStyleSheet("color:#6c7086; font-size:11px;")
        title_row.addWidget(self._status)
        outer.addLayout(title_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(8)
        self._scroll.setWidget(self._body)
        self._scroll.setMinimumSize(400, 120)
        self._scroll.setMaximumHeight(480)
        outer.addWidget(self._scroll, 1)

        btns = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        btns.addWidget(refresh)
        settings = QPushButton("Settings…")
        settings.clicked.connect(self._open_settings)
        btns.addWidget(settings)
        btns.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        btns.addWidget(close_btn)
        outer.addLayout(btns)

        self.setMinimumWidth(420)
        self.resize(440, 320)

    def show_at_cursor(self) -> None:
        self.reload()
        pos = QCursor.pos()
        # Place below-left of cursor; keep on screen.
        geo = self.frameGeometry()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            x = min(max(pos.x() - geo.width() // 2, avail.left() + 8), avail.right() - geo.width() - 8)
            y = min(max(pos.y() + 12, avail.top() + 8), avail.bottom() - geo.height() - 8)
            self.move(QPoint(x, y))
        else:
            self.move(pos + QPoint(-100, 12))
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def reload(self) -> None:
        self._status.setText("loading…")
        QApplication.processEvents()
        try:
            self._views = fetch_usage_views(self._host, self._port, prefer_cli=True)
        except Exception as exc:
            logger.warning("reload failed: %s", exc)
            self._views = []
        self._rebuild()

    def _rebuild(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        binary = find_codexbar_binary()
        if not self._views:
            msg = QLabel(
                "No usage data.\n"
                + (
                    f"CLI: {binary}"
                    if binary
                    else "Install official codexbar CLI from GitHub Releases."
                )
            )
            msg.setWordWrap(True)
            msg.setStyleSheet("color:#f38ba8;")
            self._body_layout.addWidget(msg)
            self._status.setText("empty")
        else:
            for v in self._views:
                self._body_layout.addWidget(_ProviderCard(v))
            self._body_layout.addStretch()
            self._status.setText(f"{len(self._views)} provider(s) · CLI")

        self._body.adjustSize()
        # Fit window height to content modestly
        hint_h = min(520, max(200, self._body.sizeHint().height() + 100))
        self.resize(self.width(), hint_h)

    def _open_settings(self) -> None:
        from codexbar_gui.config_dialog import ConfigDialog

        dlg = ConfigDialog(self._host, self._port, parent=self)
        dlg.exec()
        self.reload()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        # Close when focus leaves (click outside), common for tray popovers.
        QTimer.singleShot(150, self._maybe_hide)
        super().focusOutEvent(event)

    def _maybe_hide(self) -> None:
        if not self.isActiveWindow():
            self.hide()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
