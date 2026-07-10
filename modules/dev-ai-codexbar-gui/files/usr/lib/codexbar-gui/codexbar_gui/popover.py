"""Wayland-safe usage popover — closer to official CodexBar menu.

- Provider tabs (Overview / Codex / Claude / …)
- Session/Weekly (+ extra windows) with pace tick on bar
- Cost Today / 30d + mini history chart
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from codexbar_gui.cost import CostView, fetch_cost
from codexbar_gui.icon_updater import paint_dual_window_pixmap
from codexbar_gui.upstream import (
    ProviderView,
    RateWindowView,
    enabled_providers_from_config,
    fetch_enabled_providers,
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
    return "#f5a97f"  # warm orange like official Claude bars


class _PaceBar(QWidget):
    """Remaining bar with green expected-pace tick (official style)."""

    def __init__(
        self,
        remaining: float,
        expected_used: Optional[float] = None,
        color: str = "#f5a97f",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._remaining = max(0.0, min(100.0, remaining))
        self._expected_used = expected_used
        self._color = color
        self.setFixedHeight(10)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(0, 1, w, h - 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#313244"))
        p.drawRoundedRect(track, h / 2, h / 2)
        fill_w = w * (self._remaining / 100.0)
        if fill_w > 0.5:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(0, 1, fill_w, h - 2), h / 2, h / 2)
        # Expected-used tick → position as remaining of linear schedule
        if self._expected_used is not None:
            exp_rem = max(0.0, min(100.0, 100.0 - self._expected_used))
            x = w * (exp_rem / 100.0)
            p.setPen(QPen(QColor("#a6e3a1"), 2.0))
            p.drawLine(int(x), 0, int(x), h)
        p.end()


class _UsageMeter(QWidget):
    def __init__(self, win: RateWindowView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 6)
        root.setSpacing(3)

        rem = win.remaining_percent
        color = _rem_color(rem)

        top = QHBoxLayout()
        name = QLabel(win.label)
        name.setFont(QFont("Sans", 11, QFont.Weight.DemiBold))
        name.setStyleSheet("color:#cdd6f4; border:none;")
        top.addWidget(name)
        top.addStretch()
        root.addLayout(top)

        bar = _PaceBar(
            remaining=rem,
            expected_used=win.pace.expected_used_percent if win.pace else None,
            color=color,
        )
        root.addWidget(bar)

        # Official: left = % left + reserve; right = resets + lasts
        mid = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.setSpacing(0)
        left = QLabel(f"{int(round(rem))}% left")
        left.setStyleSheet(f"color:{color}; border:none; font-size:12px; font-weight:600;")
        left_col.addWidget(left)
        if win.pace is not None:
            st = win.pace.status
            pc = (
                "#a6e3a1"
                if st == "reserve"
                else "#fab387"
                if st == "deficit"
                else "#94e2d5"
            )
            # Short official-style: "52% in reserve"
            if st == "reserve":
                short = f"{int(round(win.pace.reserve_percent))}% in reserve"
            elif st == "deficit":
                short = f"{int(round(-win.pace.reserve_percent))}% over pace"
            else:
                short = "On pace"
            pl = QLabel(short)
            pl.setStyleSheet(f"color:{pc}; border:none; font-size:11px; font-weight:600;")
            left_col.addWidget(pl)
        mid.addLayout(left_col, 1)

        right_col = QVBoxLayout()
        right_col.setSpacing(0)
        resets = QLabel(win.resets_in or "")
        resets.setAlignment(Qt.AlignmentFlag.AlignRight)
        resets.setStyleSheet("color:#a6adc8; border:none; font-size:11px;")
        right_col.addWidget(resets)
        if win.pace is not None:
            lasts = (
                "Lasts until reset"
                if win.pace.will_last_to_reset
                else "May run out early"
            )
            ll = QLabel(lasts)
            ll.setAlignment(Qt.AlignmentFlag.AlignRight)
            ll.setStyleSheet("color:#6c7086; border:none; font-size:11px;")
            right_col.addWidget(ll)
        mid.addLayout(right_col)
        root.addLayout(mid)


class _CostChart(QWidget):
    """Mini daily cost bars (official cost history)."""

    def __init__(self, cost: CostView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cost = cost
        self.setMinimumHeight(72)
        self.setMaximumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#181825"))
        days = self._cost.daily[-30:] if self._cost.daily else []
        if not days:
            p.setPen(QColor("#6c7086"))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No cost history")
            p.end()
            return
        peak = max((d.total_cost for d in days), default=1.0) or 1.0
        n = len(days)
        gap = 2.0
        bar_w = max(2.0, (w - 8 - gap * (n - 1)) / n)
        x = 4.0
        for d in days:
            bh = max(1.0, (h - 12) * (d.total_cost / peak))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f5a97f"))
            p.drawRoundedRect(QRectF(x, h - 6 - bh, bar_w, bh), 1.5, 1.5)
            x += bar_w + gap
        p.setPen(QColor("#6c7086"))
        p.setFont(QFont("Sans", 8))
        p.drawText(
            4,
            h - 2,
            f"Est. total ({self._cost.history_days}d): ${self._cost.period_cost:,.2f}",
        )
        p.end()


class _SectionTitle(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet(
            "color:#6c7086; border:none; font-size:10px; font-weight:700; "
            "letter-spacing:0.06em;"
        )


class _ProviderCard(QFrame):
    def __init__(
        self,
        view: ProviderView,
        cost: Optional[CostView] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ProviderCard")
        self.setStyleSheet(
            "#ProviderCard { background:#1e1e2e; border:1px solid #313244; "
            "border-radius:12px; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(6)

        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = QLabel(view.display_name)
        name.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        name.setStyleSheet("color:#cdd6f4; border:none;")
        title_col.addWidget(name)
        sub_bits = [view.updated_label or "", view.source or ""]
        sub = QLabel(" · ".join(b for b in sub_bits if b))
        sub.setStyleSheet("color:#6c7086; border:none; font-size:11px;")
        title_col.addWidget(sub)
        head.addLayout(title_col, 1)

        right = QVBoxLayout()
        if view.plan_label:
            badge = QLabel(view.plan_label)
            badge.setAlignment(Qt.AlignmentFlag.AlignRight)
            badge.setStyleSheet(
                "color:#cba6f7; border:none; font-size:12px; font-weight:600;"
            )
            right.addWidget(badge)
        if view.account:
            acc = QLabel(view.account)
            acc.setAlignment(Qt.AlignmentFlag.AlignRight)
            acc.setStyleSheet("color:#a6adc8; border:none; font-size:11px;")
            right.addWidget(acc)
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

        for win in view.all_windows():
            root.addWidget(_UsageMeter(win))

        if view.credits_remaining is not None:
            root.addWidget(_SectionTitle("Credits"))
            c = QLabel(f"{view.credits_remaining:g} left")
            c.setStyleSheet("color:#cdd6f4; border:none; font-size:12px;")
            root.addWidget(c)

        if cost is not None and not cost.error:
            root.addWidget(_SectionTitle("Cost"))
            today = QLabel(cost.today_line)
            today.setStyleSheet("color:#cdd6f4; border:none; font-size:12px;")
            root.addWidget(today)
            period = QLabel(cost.period_line)
            period.setStyleSheet("color:#a6adc8; border:none; font-size:11px;")
            root.addWidget(period)
            if cost.daily:
                root.addWidget(_CostChart(cost))
        elif cost is not None and cost.error:
            root.addWidget(_SectionTitle("Cost"))
            e = QLabel(cost.error[:120])
            e.setStyleSheet("color:#6c7086; border:none; font-size:11px;")
            root.addWidget(e)


class _ReloadWorker(QThread):
    done = Signal(list, dict)  # views, costs_by_provider

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port

    def run(self) -> None:
        try:
            views = fetch_enabled_providers(timeout=35.0)
        except Exception:
            logger.warning("reload failed", exc_info=True)
            views = []
        costs: Dict[str, CostView] = {}
        for v in views:
            if not v.ok:
                continue
            # Cost scan is local logs — Claude has data; codex often empty
            try:
                c = fetch_cost(provider=v.provider, days=30, timeout=40.0)
            except Exception:
                c = None
            if c is not None:
                costs[v.provider] = c
        self.done.emit(views, costs)


class UsagePopover(QWidget):
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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._host = host
        self._port = port
        self._web_url = web_url
        self._views: List[ProviderView] = []
        self._costs: Dict[str, CostView] = {}
        self._active: Optional[str] = None  # provider id or "overview"
        self._worker: Optional[_ReloadWorker] = None
        self._tab_buttons: Dict[str, QPushButton] = {}

        self.setStyleSheet(
            "#CodexBarPopover { background:#11111b; border:1px solid #45475a; "
            "border-radius:12px; }"
            "QLabel { color:#cdd6f4; }"
            "QPushButton { background:#313244; color:#cdd6f4; border:none; "
            "padding:6px 10px; border-radius:8px; font-size:12px; }"
            "QPushButton:hover { background:#45475a; }"
            "QPushButton#tabActive { background:#89b4fa; color:#11111b; font-weight:600; }"
            "QPushButton#tabIdle { background:#1e1e2e; color:#a6adc8; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._tabs = QHBoxLayout()
        self._tabs.setContentsMargins(10, 10, 10, 4)
        self._tabs.setSpacing(6)
        tab_host = QWidget()
        tab_host.setLayout(self._tabs)
        outer.addWidget(tab_host)

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
        self._scroll.setMinimumWidth(400)
        self._scroll.setMaximumHeight(560)
        outer.addWidget(self._scroll, 1)

        actions = QVBoxLayout()
        actions.setContentsMargins(10, 4, 10, 10)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#313244; border:none;")
        actions.addWidget(sep)
        self._status = QLabel("")
        self._status.setStyleSheet("color:#6c7086; font-size:10px; border:none;")
        actions.addWidget(self._status)

        row = QHBoxLayout()
        refresh = QPushButton("↻  Refresh")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        self._web_btn = QPushButton("Usage Dashboard")
        self._web_btn.clicked.connect(self._open_web)
        row.addWidget(self._web_btn)
        actions.addLayout(row)
        settings = QPushButton("Settings…")
        settings.clicked.connect(self._open_settings)
        actions.addWidget(settings)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        actions.addWidget(close_btn)
        outer.addLayout(actions)

        self._set_web_url(web_url)
        self.setMinimumWidth(420)
        self.resize(440, 560)

    def set_web_url(self, url: Optional[str]) -> None:
        self._set_web_url(url)

    def _set_web_url(self, url: Optional[str]) -> None:
        self._web_url = url
        if hasattr(self, "_web_btn"):
            self._web_btn.setEnabled(bool(url))
            self._web_btn.setToolTip(url or "Web UI not running")

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
        self._status.setText("loading providers + cost…")
        self._worker = _ReloadWorker(self._host, self._port, parent=self)
        self._worker.done.connect(self._on_reload_done)
        self._worker.start()

    def _on_reload_done(self, views: list, costs: dict) -> None:
        self._views = list(views)
        self._costs = dict(costs)
        if self._active is None or (
            self._active != "overview"
            and self._active not in {v.provider for v in self._views}
        ):
            self._active = self._views[0].provider if self._views else "overview"
        self._rebuild_tabs()
        self._rebuild_body()

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear(item.layout())

    def _rebuild_tabs(self) -> None:
        self._clear(self._tabs)
        self._tab_buttons.clear()
        if len(self._views) > 1:
            self._add_tab("overview", "Overview")
        for v in self._views:
            self._add_tab(v.provider, v.display_name)
        self._tabs.addStretch()
        self._paint_tabs()

    def _add_tab(self, key: str, title: str) -> None:
        btn = QPushButton(title)
        btn.setObjectName("tabIdle")
        btn.clicked.connect(lambda checked=False, k=key: self._select_tab(k))
        self._tab_buttons[key] = btn
        self._tabs.addWidget(btn)

    def _select_tab(self, key: str) -> None:
        self._active = key
        self._paint_tabs()
        self._rebuild_body()

    def _paint_tabs(self) -> None:
        for k, btn in self._tab_buttons.items():
            btn.setObjectName("tabActive" if k == self._active else "tabIdle")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _rebuild_body(self) -> None:
        self._clear(self._body_layout)
        binary = find_codexbar_binary()
        if not self._views:
            msg = QLabel(
                "No usage data.\n"
                + (f"CLI: {binary}" if binary else "Install official codexbar CLI.")
            )
            msg.setWordWrap(True)
            msg.setStyleSheet("color:#f38ba8;")
            self._body_layout.addWidget(msg)
            self._status.setText("empty")
            return

        if self._active == "overview":
            for v in self._views:
                # Compact overview rows
                row = QFrame()
                row.setStyleSheet(
                    "QFrame { background:#1e1e2e; border:1px solid #313244; "
                    "border-radius:10px; }"
                )
                hl = QHBoxLayout(row)
                hl.setContentsMargins(10, 8, 10, 8)
                title = QLabel(f"<b>{v.display_name}</b>")
                hl.addWidget(title)
                if v.ok and v.headline_remaining is not None:
                    rem = QLabel(f"{int(round(v.headline_remaining))}% left")
                    rem.setStyleSheet(f"color:{_rem_color(v.headline_remaining)};")
                    hl.addWidget(rem)
                elif v.error:
                    err = QLabel(v.error[:40])
                    err.setStyleSheet("color:#f38ba8; font-size:11px;")
                    hl.addWidget(err)
                hl.addStretch()
                open_btn = QPushButton("Open")
                open_btn.clicked.connect(
                    lambda checked=False, p=v.provider: self._select_tab(p)
                )
                hl.addWidget(open_btn)
                self._body_layout.addWidget(row)
        else:
            view = next(
                (v for v in self._views if v.provider == self._active),
                self._views[0],
            )
            cost = self._costs.get(view.provider)
            self._body_layout.addWidget(_ProviderCard(view, cost=cost))

        self._body_layout.addStretch()
        self._status.setText(
            f"{len(self._views)} provider(s) · CLI"
            + (f" · {self._web_url}" if self._web_url else "")
        )
        self._body.adjustSize()
        hint_h = min(620, max(360, self._body.sizeHint().height() + 180))
        self.resize(max(self.width(), 440), hint_h)

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
