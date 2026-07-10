"""Wayland-safe usage popover — refined to read closer to official CodexBar.

Visual language: soft dark surface, pill tabs, calm meters, menu-style footer.
Data stays official ``codexbar`` CLI only.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
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
    fetch_enabled_providers,
    find_codexbar_binary,
)

logger = logging.getLogger("codexbar_gui.popover")

# Refined palette (dark, not muddy)
C = {
    "bg": "#0f1117",
    "surface": "#171a22",
    "card": "#1c2030",
    "card2": "#222838",
    "border": "#2a3144",
    "text": "#e8ecf4",
    "muted": "#9aa3b5",
    "dim": "#6b7385",
    "accent": "#7aa2f7",
    "accent2": "#9d7cd8",
    "good": "#9ece6a",
    "warn": "#e0af68",
    "bad": "#f7768e",
    "bar": "#e0af68",
    "track": "#2a3144",
}


def _rem_color(rem: Optional[float]) -> str:
    if rem is None:
        return C["dim"]
    if rem <= 20:
        return C["bad"]
    if rem <= 50:
        return C["warn"]
    return C["bar"]


class _PaceBar(QWidget):
    """Remaining fill + green expected-pace tick."""

    def __init__(
        self,
        remaining: float,
        expected_used: Optional[float] = None,
        color: str = C["bar"],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._remaining = max(0.0, min(100.0, remaining))
        self._expected_used = expected_used
        self._color = color
        self.setFixedHeight(9)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        track = QRectF(0, 1.5, w, h - 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["track"]))
        p.drawRoundedRect(track, h / 2, h / 2)
        fill_w = w * (self._remaining / 100.0)
        if fill_w > 0.5:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(0, 1.5, fill_w, h - 3), h / 2, h / 2)
        if self._expected_used is not None:
            exp_rem = max(0.0, min(100.0, 100.0 - self._expected_used))
            x = w * (exp_rem / 100.0)
            p.setPen(QPen(QColor(C["good"]), 2.0))
            p.drawLine(int(round(x)), 0, int(round(x)), int(h))
        p.end()


class _UsageMeter(QWidget):
    def __init__(self, win: RateWindowView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 6)
        root.setSpacing(4)

        rem = win.remaining_percent
        color = _rem_color(rem)

        title = QLabel(win.label)
        title.setFont(QFont("Sans", 11, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color:{C['text']}; border:none; background:transparent;")
        root.addWidget(title)

        root.addWidget(
            _PaceBar(
                remaining=rem,
                expected_used=win.pace.expected_used_percent if win.pace else None,
                color=color,
            )
        )

        row = QHBoxLayout()
        row.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(1)
        pct = QLabel(f"{int(round(rem))}% left")
        pct.setStyleSheet(
            f"color:{color}; border:none; background:transparent; "
            f"font-size:12px; font-weight:600;"
        )
        left.addWidget(pct)
        if win.pace is not None:
            st = win.pace.status
            if st == "reserve":
                short = f"{int(round(win.pace.reserve_percent))}% in reserve"
                pc = C["good"]
            elif st == "deficit":
                short = f"{int(round(-win.pace.reserve_percent))}% over pace"
                pc = C["warn"]
            else:
                short = "On pace"
                pc = C["muted"]
            pl = QLabel(short)
            pl.setStyleSheet(
                f"color:{pc}; border:none; background:transparent; "
                f"font-size:11px; font-weight:600;"
            )
            left.addWidget(pl)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(1)
        resets = QLabel(win.resets_in or "")
        resets.setAlignment(Qt.AlignmentFlag.AlignRight)
        resets.setStyleSheet(
            f"color:{C['muted']}; border:none; background:transparent; font-size:11px;"
        )
        right.addWidget(resets)
        if win.pace is not None:
            if win.pace.status == "deficit":
                lasts = "May run out early"
            else:
                lasts = "Lasts until reset"
            ll = QLabel(lasts)
            ll.setAlignment(Qt.AlignmentFlag.AlignRight)
            ll.setStyleSheet(
                f"color:{C['dim']}; border:none; background:transparent; font-size:11px;"
            )
            right.addWidget(ll)
        row.addLayout(right)
        root.addLayout(row)


class _CostChart(QWidget):
    def __init__(self, cost: CostView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cost = cost
        self.setMinimumHeight(78)
        self.setMaximumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["card2"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), 10, 10)
        days = self._cost.daily[-30:] if self._cost.daily else []
        if not days:
            p.setPen(QColor(C["dim"]))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No cost history")
            p.end()
            return
        peak = max((d.total_cost for d in days), default=1.0) or 1.0
        n = len(days)
        pad = 10.0
        gap = 2.0
        usable = w - pad * 2
        bar_w = max(2.5, (usable - gap * (n - 1)) / max(n, 1))
        x = pad
        base_y = h - 18
        for d in days:
            bh = max(2.0, (base_y - 10) * (d.total_cost / peak))
            p.setBrush(QColor(C["bar"]))
            p.drawRoundedRect(QRectF(x, base_y - bh, bar_w, bh), 2, 2)
            x += bar_w + gap
        p.setPen(QColor(C["dim"]))
        p.setFont(QFont("Sans", 8))
        p.drawText(
            int(pad),
            int(h - 5),
            f"Est. total ({self._cost.history_days}d): ${self._cost.period_cost:,.2f}",
        )
        p.end()


class _MenuButton(QPushButton):
    """Flat list-style action row (official footer)."""

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(
            f"QPushButton {{"
            f"  text-align: left; padding: 9px 12px; border: none; border-radius: 8px;"
            f"  background: transparent; color: {C['text']}; font-size: 12.5px;"
            f"}}"
            f"QPushButton:hover {{ background: {C['card2']}; }}"
            f"QPushButton:disabled {{ color: {C['dim']}; }}"
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
            f"#ProviderCard {{"
            f"  background: {C['card']}; border: 1px solid {C['border']};"
            f"  border-radius: 14px;"
            f"}}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = QLabel(view.display_name)
        name.setFont(QFont("Sans", 15, QFont.Weight.Bold))
        name.setStyleSheet(f"color:{C['text']}; border:none; background:transparent;")
        title_col.addWidget(name)
        sub = QLabel(view.updated_label or view.source or "")
        sub.setStyleSheet(f"color:{C['dim']}; border:none; background:transparent; font-size:11px;")
        title_col.addWidget(sub)
        head.addLayout(title_col, 1)

        right = QVBoxLayout()
        right.setSpacing(3)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        if view.plan_label:
            badge = QLabel(view.plan_label)
            badge.setAlignment(Qt.AlignmentFlag.AlignRight)
            badge.setStyleSheet(
                f"color:{C['accent2']}; border:none; background:transparent; "
                f"font-size:12px; font-weight:600;"
            )
            right.addWidget(badge)
        if view.account:
            acc = QLabel(view.account)
            acc.setAlignment(Qt.AlignmentFlag.AlignRight)
            acc.setStyleSheet(
                f"color:{C['muted']}; border:none; background:transparent; font-size:11px;"
            )
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
                size=34,
                credits_remaining=view.credits_remaining,
            )
        )
        right.addWidget(icon, 0, Qt.AlignmentFlag.AlignRight)
        head.addLayout(right)
        root.addLayout(head)
        root.addSpacing(4)

        if view.error and not view.ok:
            box = QFrame()
            box.setStyleSheet(
                f"QFrame {{ background:{C['card2']}; border-radius:10px; "
                f"border:1px solid {C['border']}; }}"
            )
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 10, 12, 10)
            t = QLabel("Couldn’t load usage")
            t.setStyleSheet(
                f"color:{C['bad']}; border:none; background:transparent; "
                f"font-weight:600; font-size:12px;"
            )
            bl.addWidget(t)
            # Friendly short reason
            msg = view.error
            if "timeout" in msg.lower():
                msg = "Timed out talking to the provider CLI. Try Refresh, or set Usage source in Settings."
            elif "not configured" in msg.lower():
                msg = "Not configured — open Settings and complete OAuth / API key."
            d = QLabel(msg)
            d.setWordWrap(True)
            d.setStyleSheet(
                f"color:{C['muted']}; border:none; background:transparent; font-size:11px;"
            )
            bl.addWidget(d)
            root.addWidget(box)
            # Still show cost if we have it
            if cost is not None and not cost.error and cost.daily:
                self._add_cost(root, cost)
            return

        for win in view.all_windows():
            root.addWidget(_UsageMeter(win))

        if view.credits_remaining is not None:
            root.addSpacing(4)
            sec = QLabel("CREDITS")
            sec.setStyleSheet(
                f"color:{C['dim']}; border:none; background:transparent; "
                f"font-size:10px; font-weight:700; letter-spacing:0.08em;"
            )
            root.addWidget(sec)
            c = QLabel(f"{view.credits_remaining:g} left")
            c.setStyleSheet(
                f"color:{C['text']}; border:none; background:transparent; font-size:12px;"
            )
            root.addWidget(c)

        if cost is not None and not cost.error:
            self._add_cost(root, cost)

    def _add_cost(self, root: QVBoxLayout, cost: CostView) -> None:
        root.addSpacing(6)
        sec = QLabel("COST")
        sec.setStyleSheet(
            f"color:{C['dim']}; border:none; background:transparent; "
            f"font-size:10px; font-weight:700; letter-spacing:0.08em;"
        )
        root.addWidget(sec)
        box = QFrame()
        box.setStyleSheet(
            f"QFrame {{ background:{C['card2']}; border-radius:10px; border:none; }}"
        )
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(3)
        today = QLabel(cost.today_line)
        today.setStyleSheet(
            f"color:{C['text']}; border:none; background:transparent; font-size:12px;"
        )
        bl.addWidget(today)
        period = QLabel(cost.period_line)
        period.setStyleSheet(
            f"color:{C['muted']}; border:none; background:transparent; font-size:11px;"
        )
        bl.addWidget(period)
        if cost.daily:
            bl.addSpacing(4)
            bl.addWidget(_CostChart(cost))
        root.addWidget(box)


class _OverviewRow(QFrame):
    def __init__(
        self,
        view: ProviderView,
        on_open,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("OverviewRow")
        self.setStyleSheet(
            f"#OverviewRow {{"
            f"  background:{C['card']}; border:1px solid {C['border']};"
            f"  border-radius:12px;"
            f"}}"
            f"#OverviewRow:hover {{ background:{C['card2']}; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(10)

        icon = QLabel()
        icon.setPixmap(
            paint_dual_window_pixmap(
                primary_remaining=(
                    view.primary.remaining_percent if view.primary else None
                ),
                secondary_remaining=(
                    view.secondary.remaining_percent if view.secondary else None
                ),
                size=28,
                credits_remaining=view.credits_remaining,
                error=not view.ok,
            )
        )
        lay.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(view.display_name)
        name.setStyleSheet(
            f"color:{C['text']}; border:none; background:transparent; "
            f"font-size:13px; font-weight:600;"
        )
        col.addWidget(name)
        if view.ok and view.headline_remaining is not None:
            rem = view.headline_remaining
            st = QLabel(f"{int(round(rem))}% left")
            st.setStyleSheet(
                f"color:{_rem_color(rem)}; border:none; background:transparent; "
                f"font-size:11px; font-weight:600;"
            )
        else:
            st = QLabel("Unavailable")
            st.setStyleSheet(
                f"color:{C['bad']}; border:none; background:transparent; font-size:11px;"
            )
            st.setToolTip(view.error or "")
        col.addWidget(st)
        lay.addLayout(col, 1)

        open_btn = QPushButton("Open")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background:{C['card2']}; color:{C['text']}; border:1px solid {C['border']};"
            f"  border-radius:8px; padding:6px 12px; font-size:11px;"
            f"}}"
            f"QPushButton:hover {{ background:{C['border']}; }}"
        )
        open_btn.clicked.connect(on_open)
        lay.addWidget(open_btn)


class _ReloadWorker(QThread):
    done = Signal(list, dict)

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port

    def run(self) -> None:
        try:
            views = fetch_enabled_providers(timeout=45.0)
        except Exception:
            logger.warning("reload failed", exc_info=True)
            views = []
        costs: Dict[str, CostView] = {}
        for v in views:
            # Cost is local and useful even when usage timed out (Claude)
            try:
                c = fetch_cost(provider=v.provider, days=30, timeout=40.0)
            except Exception:
                c = None
            if c is not None and (c.daily or c.period_cost or c.today_tokens):
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
        self._active: Optional[str] = None
        self._worker: Optional[_ReloadWorker] = None
        self._tab_buttons: Dict[str, QPushButton] = {}

        self.setStyleSheet(
            f"#CodexBarPopover {{"
            f"  background: {C['bg']};"
            f"  border: 1px solid {C['border']};"
            f"  border-radius: 16px;"
            f"}}"
            f"QLabel {{ color: {C['text']}; background: transparent; }}"
            f"QScrollBar:vertical {{ width: 8px; background: transparent; }}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {C['border']}; border-radius: 4px; min-height: 24px;"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        # Soft shadow when compositor allows
        try:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(28)
            shadow.setOffset(0, 10)
            shadow.setColor(QColor(0, 0, 0, 140))
            self.setGraphicsEffect(shadow)
        except Exception:
            pass

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Pill tab track
        tab_wrap = QFrame()
        tab_wrap.setObjectName("TabTrack")
        tab_wrap.setStyleSheet(
            f"#TabTrack {{"
            f"  background: {C['surface']};"
            f"  border-bottom: 1px solid {C['border']};"
            f"  border-top-left-radius: 16px; border-top-right-radius: 16px;"
            f"}}"
        )
        tab_outer = QVBoxLayout(tab_wrap)
        tab_outer.setContentsMargins(12, 12, 12, 10)
        self._tab_track = QFrame()
        self._tab_track.setObjectName("PillTrack")
        self._tab_track.setStyleSheet(
            f"#PillTrack {{"
            f"  background: {C['card']}; border: 1px solid {C['border']};"
            f"  border-radius: 11px;"
            f"}}"
        )
        self._tabs = QHBoxLayout(self._tab_track)
        self._tabs.setContentsMargins(3, 3, 3, 3)
        self._tabs.setSpacing(2)
        tab_outer.addWidget(self._tab_track)
        outer.addWidget(tab_wrap)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea QWidget { background: transparent; }"
        )
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 12, 14, 8)
        self._body_layout.setSpacing(10)
        self._scroll.setWidget(self._body)
        self._scroll.setMinimumWidth(400)
        self._scroll.setMaximumHeight(540)
        outer.addWidget(self._scroll, 1)

        # Menu footer
        foot = QFrame()
        foot.setObjectName("Footer")
        foot.setStyleSheet(
            f"#Footer {{"
            f"  background: {C['surface']};"
            f"  border-top: 1px solid {C['border']};"
            f"  border-bottom-left-radius: 16px; border-bottom-right-radius: 16px;"
            f"}}"
        )
        actions = QVBoxLayout(foot)
        actions.setContentsMargins(8, 6, 8, 8)
        actions.setSpacing(1)
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color:{C['dim']}; font-size:10px; border:none; padding: 2px 10px 6px;"
        )
        actions.addWidget(self._status)

        self._btn_refresh = _MenuButton("  ↻    Refresh")
        self._btn_refresh.clicked.connect(self.reload)
        actions.addWidget(self._btn_refresh)
        self._web_btn = _MenuButton("  ⌗    Usage Dashboard")
        self._web_btn.clicked.connect(self._open_web)
        actions.addWidget(self._web_btn)
        self._btn_settings = _MenuButton("  ⚙    Settings…")
        self._btn_settings.clicked.connect(self._open_settings)
        actions.addWidget(self._btn_settings)
        self._btn_close = _MenuButton("  ✕    Close")
        self._btn_close.clicked.connect(self.hide)
        actions.addWidget(self._btn_close)
        outer.addWidget(foot)

        self._set_web_url(web_url)
        self.setMinimumWidth(400)
        self.resize(420, 560)

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
            self._status.setText("Loading…")
            return
        self._status.setText("Loading providers…")
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
            # Prefer overview when multi, else first provider
            self._active = (
                "overview" if len(self._views) > 1 else (self._views[0].provider if self._views else "overview")
            )
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
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(True)
        btn.clicked.connect(lambda checked=False, k=key: self._select_tab(k))
        self._tab_buttons[key] = btn
        self._tabs.addWidget(btn)

    def _select_tab(self, key: str) -> None:
        self._active = key
        self._paint_tabs()
        self._rebuild_body()

    def _paint_tabs(self) -> None:
        for k, btn in self._tab_buttons.items():
            active = k == self._active
            btn.setChecked(active)
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {C['accent']}; color: #0b0d12; border: none;"
                    f"  border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600;"
                    f"}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: transparent; color: {C['muted']}; border: none;"
                    f"  border-radius: 8px; padding: 6px 12px; font-size: 12px;"
                    f"}}"
                    f"QPushButton:hover {{ color: {C['text']}; background: {C['card2']}; }}"
                )

    def _rebuild_body(self) -> None:
        self._clear(self._body_layout)
        binary = find_codexbar_binary()
        if not self._views:
            empty = QFrame()
            empty.setStyleSheet(
                f"QFrame {{ background:{C['card']}; border-radius:12px; "
                f"border:1px solid {C['border']}; }}"
            )
            el = QVBoxLayout(empty)
            el.setContentsMargins(16, 20, 16, 20)
            t = QLabel("No usage data")
            t.setStyleSheet(
                f"color:{C['text']}; font-weight:600; border:none; background:transparent;"
            )
            el.addWidget(t)
            d = QLabel(
                f"CLI: {binary}" if binary else "Install official codexbar CLI."
            )
            d.setWordWrap(True)
            d.setStyleSheet(
                f"color:{C['muted']}; border:none; background:transparent; font-size:11px;"
            )
            el.addWidget(d)
            self._body_layout.addWidget(empty)
            self._status.setText("Empty")
            return

        if self._active == "overview":
            for v in self._views:
                self._body_layout.addWidget(
                    _OverviewRow(
                        v,
                        on_open=lambda p=v.provider: self._select_tab(p),
                    )
                )
        else:
            view = next(
                (v for v in self._views if v.provider == self._active),
                self._views[0],
            )
            cost = self._costs.get(view.provider)
            self._body_layout.addWidget(_ProviderCard(view, cost=cost))

        self._body_layout.addStretch()
        ok_n = sum(1 for v in self._views if v.ok)
        self._status.setText(
            f"{ok_n}/{len(self._views)} providers · official CLI"
            + (f" · web {self._web_url.replace('http://', '')}" if self._web_url else "")
        )
        self._body.adjustSize()
        hint_h = min(640, max(360, self._body.sizeHint().height() + 170))
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
