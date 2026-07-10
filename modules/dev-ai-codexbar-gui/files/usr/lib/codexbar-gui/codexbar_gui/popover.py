"""Wayland-safe usage popover — layout mirrors official CodexBar menu.

Official (macOS) menu shows provider header + account/plan, Session/Weekly
meters with ``Resets in …``, pace/reserve, credits, then actions.
We do not reimplement OAuth; data is official ``codexbar usage`` JSON only.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from codexbar_gui.icon_updater import paint_dual_window_pixmap
from codexbar_gui.upstream import (
    ProviderView,
    RateWindowView,
    fetch_usage_views,
    find_codexbar_binary,
)

logger = logging.getLogger("codexbar_gui.popover")


def _rem_color(rem: Optional[float]) -> str:
    if rem is None:
        return "#6c7086"
    if rem <= 20:
        return "#f38ba8"
    if rem <= 50:
        return "#fab387"
    return "#89dceb"  # cyan like official Codex bars


class _UsageMeter(QWidget):
    """One Session/Weekly row — official: label · % left · bar · Resets in."""

    def __init__(self, win: RateWindowView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 6)
        root.setSpacing(4)

        rem = win.remaining_percent
        used = win.used_percent
        color = _rem_color(rem)

        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(win.label.replace(" (5h)", ""))
        name.setFont(QFont("Sans", 11, QFont.Weight.DemiBold))
        name.setStyleSheet("color:#cdd6f4; border:none;")
        name.setFixedWidth(72)
        top.addWidget(name)

        # Official Codex settings panel: "98% left" on the bar line
        left = QLabel(f"{int(round(rem))}% left")
        left.setStyleSheet(f"color:{color}; border:none; font-size:12px; font-weight:600;")
        top.addWidget(left)
        top.addStretch()

        resets = QLabel(win.resets_in or win.reset_description or "")
        resets.setStyleSheet("color:#a6adc8; border:none; font-size:11px;")
        resets.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(resets)
        root.addLayout(top)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(rem)))
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{ background:#313244; border:none; border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{color}; border-radius:4px; }}"
        )
        root.addWidget(bar)

        # Pace/reserve — the official "am I burning too fast?" line
        if win.pace is not None:
            st = win.pace.status
            if st == "reserve":
                pace_color = "#a6e3a1"
            elif st == "deficit":
                pace_color = "#fab387"
            else:
                pace_color = "#94e2d5"
            pace_row = QHBoxLayout()
            pace_l = QLabel(win.pace.summary)
            pace_l.setWordWrap(True)
            pace_l.setStyleSheet(
                f"color:{pace_color}; border:none; font-size:12px; font-weight:600;"
            )
            pace_row.addWidget(pace_l, 1)
            root.addLayout(pace_row)

        # Secondary line: used % + absolute reset clock
        sub = QHBoxLayout()
        used_l = QLabel(f"{int(round(used))}% used")
        used_l.setStyleSheet("color:#6c7086; border:none; font-size:11px;")
        sub.addWidget(used_l)
        if win.pace is not None:
            exp = QLabel(f"expected ~{int(round(win.pace.expected_used_percent))}% used")
            exp.setStyleSheet("color:#585b70; border:none; font-size:10px;")
            sub.addWidget(exp)
        if win.reset_description and win.resets_in:
            abs_t = QLabel(win.reset_description)
            abs_t.setStyleSheet("color:#585b70; border:none; font-size:10px;")
            abs_t.setAlignment(Qt.AlignmentFlag.AlignRight)
            sub.addStretch()
            sub.addWidget(abs_t)
        else:
            sub.addStretch()
        root.addLayout(sub)


class _SectionTitle(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet(
            "color:#6c7086; border:none; font-size:10px; font-weight:700; "
            "letter-spacing:0.06em; text-transform:uppercase;"
        )


class _ProviderCard(QFrame):
    """Matches official provider panel: header, Usage meters, Credits."""

    def __init__(self, view: ProviderView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProviderCard")
        self.setStyleSheet(
            "#ProviderCard { background:#1e1e2e; border:1px solid #313244; "
            "border-radius:12px; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Header: name · freshness | account · plan badge
        head = QHBoxLayout()
        head.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = QLabel(view.display_name)
        name.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        name.setStyleSheet("color:#cdd6f4; border:none;")
        title_col.addWidget(name)
        sub_bits = []
        if view.version:
            sub_bits.append(view.version)
        if view.source:
            sub_bits.append(view.source)
        if view.updated_label:
            sub_bits.append(view.updated_label)
        if view.data_confidence:
            sub_bits.append(view.data_confidence)
        sub = QLabel(" · ".join(sub_bits) if sub_bits else "")
        sub.setStyleSheet("color:#6c7086; border:none; font-size:11px;")
        title_col.addWidget(sub)
        head.addLayout(title_col, 1)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        if view.account:
            acc = QLabel(view.account)
            acc.setStyleSheet("color:#a6adc8; border:none; font-size:11px;")
            acc.setAlignment(Qt.AlignmentFlag.AlignRight)
            right.addWidget(acc)
        if view.plan_label:
            badge = QLabel(view.plan_label)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                "background:#313244; color:#cba6f7; border:none; border-radius:6px; "
                "padding:2px 8px; font-size:11px; font-weight:600;"
            )
            right.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight)
        # Dual-window meter icon (session + weekly)
        icon = QLabel()
        icon.setPixmap(
            paint_dual_window_pixmap(
                primary_remaining=(
                    view.primary.remaining_percent if view.primary else None
                ),
                secondary_remaining=(
                    view.secondary.remaining_percent if view.secondary else None
                ),
                size=36,
                credits_remaining=view.credits_remaining,
            )
        )
        right.addWidget(icon, 0, Qt.AlignmentFlag.AlignRight)
        head.addLayout(right)
        root.addLayout(head)

        if view.error:
            err = QLabel(view.error)
            err.setWordWrap(True)
            err.setStyleSheet("color:#f38ba8; border:none; font-size:12px;")
            root.addWidget(err)
            return

        # Usage section
        root.addWidget(_SectionTitle("Usage"))
        for win in (view.primary, view.secondary, view.tertiary):
            if win is not None:
                root.addWidget(_UsageMeter(win))

        # Credits (always show when we have a value — including 0)
        root.addWidget(_SectionTitle("Credits"))
        cred_row = QHBoxLayout()
        if view.credits_remaining is not None:
            c = QLabel(f"{view.credits_remaining:g} left")
            c.setStyleSheet("color:#cdd6f4; border:none; font-size:12px;")
            cred_row.addWidget(c)
        else:
            cred_row.addWidget(QLabel("—"))
        cred_row.addStretch()
        if view.reset_credits_available is not None:
            rc = QLabel(f"Limit reset credits: {view.reset_credits_available} available")
            rc.setStyleSheet("color:#a6adc8; border:none; font-size:11px;")
            cred_row.addWidget(rc)
        root.addLayout(cred_row)


class UsagePopover(QWidget):
    """Frameless tool window shown near the tray / cursor."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        web_url: Optional[str] = None,
    ) -> None:
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
        self._web_url = web_url
        self._views: List[ProviderView] = []
        self._worker: Optional[_ReloadWorker] = None

        self.setStyleSheet(
            "#CodexBarPopover {"
            "  background:#11111b;"
            "  border:1px solid #45475a;"
            "  border-radius:12px;"
            "}"
            "QLabel { color:#cdd6f4; }"
            "QPushButton {"
            "  background:transparent; color:#cdd6f4; border:none;"
            "  padding:8px 10px; border-radius:6px; text-align:left;"
            "  font-size:12px;"
            "}"
            "QPushButton:hover { background:#313244; }"
            "QPushButton#primaryBtn {"
            "  background:#313244; padding:7px 12px;"
            "}"
            "QPushButton#primaryBtn:hover { background:#45475a; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Provider tab strip (single provider today; layout ready for more)
        self._tabs = QHBoxLayout()
        self._tabs.setContentsMargins(12, 10, 12, 6)
        self._tabs.setSpacing(6)
        self._tab_host = QWidget()
        self._tab_host.setLayout(self._tabs)
        outer.addWidget(self._tab_host)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }"
            "QScrollArea QWidget { background:transparent; }"
        )
        self._scroll.viewport().setStyleSheet("background:transparent;")
        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(12, 4, 12, 8)
        self._body_layout.setSpacing(10)
        self._scroll.setWidget(self._body)
        self._scroll.setMinimumWidth(380)
        self._scroll.setMaximumHeight(520)
        outer.addWidget(self._scroll, 1)

        # Action list like official menu footer
        actions = QVBoxLayout()
        actions.setContentsMargins(8, 4, 8, 10)
        actions.setSpacing(0)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#313244; border:none;")
        actions.addWidget(sep)

        self._status = QLabel("")
        self._status.setStyleSheet(
            "color:#6c7086; font-size:10px; border:none; padding:4px 8px;"
        )
        actions.addWidget(self._status)

        row = QHBoxLayout()
        row.setSpacing(6)
        refresh = QPushButton("↻  Refresh Now")
        refresh.setObjectName("primaryBtn")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        self._web_btn = QPushButton("Usage Dashboard")
        self._web_btn.setObjectName("primaryBtn")
        self._web_btn.clicked.connect(self._open_web)
        row.addWidget(self._web_btn)
        actions.addLayout(row)

        settings = QPushButton("⚙  Settings…")
        settings.clicked.connect(self._open_settings)
        actions.addWidget(settings)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        actions.addWidget(close_btn)
        outer.addLayout(actions)

        self._web_label = QLabel("")  # kept for set_web_url API
        self._web_label.hide()
        self._set_web_url(web_url)

        self.setMinimumWidth(400)
        self.resize(420, 480)

    def set_web_url(self, url: Optional[str]) -> None:
        self._set_web_url(url)

    def _set_web_url(self, url: Optional[str]) -> None:
        self._web_url = url
        if hasattr(self, "_web_btn"):
            self._web_btn.setEnabled(bool(url))
            tip = url or "Web UI not running (start codexbar-gui)"
            self._web_btn.setToolTip(tip)

    def _open_web(self) -> None:
        if not self._web_url:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(self._web_url))

    def show_at_cursor(self) -> None:
        self.reload()
        pos = QCursor.pos()
        geo = self.frameGeometry()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            x = min(
                max(pos.x() - geo.width() // 2, avail.left() + 8),
                avail.right() - geo.width() - 8,
            )
            y = min(
                max(pos.y() + 12, avail.top() + 8),
                avail.bottom() - geo.height() - 8,
            )
            self.move(QPoint(x, y))
        else:
            self.move(pos + QPoint(-100, 12))
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def reload(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._status.setText("loading…")
            return
        self._status.setText("loading…")
        self._worker = _ReloadWorker(self._host, self._port, parent=self)
        self._worker.done.connect(self._on_reload_done)
        self._worker.start()

    def _on_reload_done(self, views: list) -> None:
        self._views = list(views)
        self._rebuild()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    def _rebuild(self) -> None:
        self._clear_layout(self._body_layout)
        self._clear_layout(self._tabs)

        binary = find_codexbar_binary()

        if not self._views:
            msg = QLabel(
                "No usage data from official CLI.\n"
                + (
                    f"CLI: {binary}"
                    if binary
                    else "Install official codexbar CLI from GitHub Releases."
                )
            )
            msg.setWordWrap(True)
            msg.setStyleSheet("color:#f38ba8; padding:12px;")
            self._body_layout.addWidget(msg)
            self._status.setText("empty")
        else:
            for v in self._views:
                tab = QLabel(f"  {v.display_name}  ")
                tab.setStyleSheet(
                    "background:#313244; color:#cdd6f4; border-radius:8px; "
                    "padding:4px 10px; font-size:12px; font-weight:600;"
                )
                self._tabs.addWidget(tab)
            self._tabs.addStretch()

            for v in self._views:
                self._body_layout.addWidget(_ProviderCard(v))
            self._body_layout.addStretch()
            self._status.setText(
                f"{len(self._views)} provider · official CLI"
                + (f" · {self._web_url}" if self._web_url else "")
            )

        self._body.adjustSize()
        hint_h = min(560, max(320, self._body.sizeHint().height() + 160))
        self.resize(max(self.width(), 420), hint_h)

    def _open_settings(self) -> None:
        from codexbar_gui.config_dialog import ConfigDialog

        dlg = ConfigDialog(self._host, self._port, parent=self)
        dlg.exec()
        self.reload()

    def focusOutEvent(self, event) -> None:  # noqa: N802
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


class _ReloadWorker(QThread):
    done = Signal(list)

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port

    def run(self) -> None:
        try:
            views = fetch_usage_views(self._host, self._port, prefer_cli=True)
        except Exception:
            logger.warning("popover reload failed", exc_info=True)
            views = []
        self.done.emit(views)
