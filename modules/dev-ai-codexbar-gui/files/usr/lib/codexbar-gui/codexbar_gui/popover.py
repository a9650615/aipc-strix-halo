"""Wayland-safe usage popover — refined to read closer to official CodexBar.

Visual language: soft dark surface, pill tabs, calm meters, menu-style footer.
Data stays official ``codexbar`` CLI only.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from codexbar_gui.cost import CostView, fetch_cost
from codexbar_gui.icon_updater import paint_dual_window_pixmap
from codexbar_gui.menu_bar import load_menu_bar_settings, order_overview_views
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
    """Remaining fill + green expected-pace tick.

    Uses child frames (not paint-only) so bars stay visible under parent
    stylesheets / Wayland compositing — custom paintEvent alone was disappearing.
    """

    def __init__(
        self,
        remaining: float,
        expected_used: Optional[float] = None,
        color: str = C["bar"],
        *,
        height: int = 12,
        min_width: int = 120,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._remaining = max(0.0, min(100.0, float(remaining)))
        self._expected_used = expected_used
        self._color = color or C["bar"]
        self._h = max(8, int(height))
        self.setFixedHeight(self._h)
        self.setMinimumWidth(min_width)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

        self._track = QFrame(self)
        self._track.setObjectName("PaceTrack")
        self._track.setStyleSheet(
            f"#PaceTrack {{"
            f"  background:{C['track']}; border:1px solid {C['border']};"
            f"  border-radius:{self._h // 2}px;"
            f"}}"
        )

        self._fill = QFrame(self._track)
        self._fill.setObjectName("PaceFill")
        self._fill.setStyleSheet(
            f"#PaceFill {{"
            f"  background:{self._color}; border:none;"
            f"  border-radius:{max(2, self._h // 2 - 1)}px;"
            f"}}"
        )

        self._tick = QFrame(self)
        self._tick.setObjectName("PaceTick")
        self._tick.setFixedWidth(2)
        self._tick.setStyleSheet(
            f"#PaceTick {{ background:{C['good']}; border:none; border-radius:1px; }}"
        )
        self._tick.setVisible(expected_used is not None)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        # inset track 1px vertically for cleaner pill
        y, th = 1, max(4, h - 2)
        self._track.setGeometry(0, y, w, th)
        fill_w = int(round(w * (self._remaining / 100.0)))
        fill_w = max(0, min(w, fill_w))
        # keep a visible nub when nearly empty but > 0
        if self._remaining > 0.5 and fill_w < 4:
            fill_w = 4
        self._fill.setGeometry(1, 1, max(0, fill_w - 2), max(2, th - 2))
        if self._expected_used is not None:
            exp_rem = max(0.0, min(100.0, 100.0 - float(self._expected_used)))
            x = int(round(w * (exp_rem / 100.0)))
            self._tick.setGeometry(max(0, min(w - 2, x)), 0, 2, h)
            self._tick.raise_()
            self._tick.show()
        else:
            self._tick.hide()

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        return QSize(max(self.minimumWidth(), 200), self._h)


# Provider accent (official-style underlines / chart fills)
_PROVIDER_ACCENT = {
    "codex": "#4ecdc4",
    "claude": "#89b4fa",
    "gemini": "#cba6f7",
    "cursor": "#f5a97f",
}


class _TabChip(QFrame):
    """Uniform tab: same height for all; provider tabs embed a mini Session bar.

    No per-tab bottom borders — active is a single solid pill (official look).
    """

    clicked = Signal()

    # One height for Overview + providers so the strip never looks staggered
    TAB_H = 48

    def __init__(
        self,
        title: str,
        *,
        accent: Optional[str] = None,
        remaining: Optional[float] = None,
        expected_used: Optional[float] = None,
        show_bar: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TabChip")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(self.TAB_H)
        self.setMinimumWidth(86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._accent = accent or C["accent"]
        self._show_bar = show_bar
        self._remaining = remaining

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(3)

        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        root.addWidget(self._title)

        # Always reserve the same bar row height so every tab is identical size
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(4)
        self._bar_host = QWidget()
        self._bar_host.setFixedHeight(10)
        self._bar_host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        bh = QHBoxLayout(self._bar_host)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(4)

        self._bar: Optional[_PaceBar] = None
        self._pct: Optional[QLabel] = None
        if show_bar:
            rem = 0.0 if remaining is None else float(remaining)
            color = _rem_color(remaining) if remaining is not None else C["dim"]
            self._bar = _PaceBar(
                remaining=rem if remaining is not None else 0.0,
                expected_used=expected_used,
                color=color if remaining is not None else C["dim"],
                height=6,
                min_width=36,
            )
            self._bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            bh.addWidget(self._bar, 1)
            self._pct = QLabel("—" if remaining is None else f"{int(round(rem))}")
            self._pct.setFixedWidth(28)
            self._pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._pct.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            bh.addWidget(self._pct)
        bar_row.addWidget(self._bar_host, 1)
        root.addLayout(bar_row)

        self.set_active(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                f"#TabChip {{"
                f"  background:{C['accent']}; border:none; border-radius:10px;"
                f"}}"
            )
            self._title.setStyleSheet(
                "color:#0b0d12; border:none; background:transparent; "
                "font-size:12px; font-weight:700;"
            )
            if self._pct is not None:
                self._pct.setStyleSheet(
                    "color:#0b0d12; border:none; background:transparent; "
                    "font-size:10px; font-weight:700;"
                )
            if self._bar is not None:
                # Active: fill stays brand-ish; track lighter on blue pill
                self._bar._track.setStyleSheet(
                    f"#PaceTrack {{ background:rgba(11,13,18,0.25); border:none; "
                    f"border-radius:3px; }}"
                )
                self._bar._fill.setStyleSheet(
                    f"#PaceFill {{ background:#0b0d12; border:none; border-radius:3px; }}"
                )
        else:
            self.setStyleSheet(
                f"#TabChip {{"
                f"  background:transparent; border:none; border-radius:10px;"
                f"}}"
                f"#TabChip:hover {{ background:{C['card2']}; }}"
            )
            self._title.setStyleSheet(
                f"color:{C['muted']}; border:none; background:transparent; "
                f"font-size:12px; font-weight:600;"
            )
            if self._pct is not None:
                color = (
                    C["dim"]
                    if self._remaining is None
                    else _rem_color(self._remaining)
                )
                self._pct.setStyleSheet(
                    f"color:{color}; border:none; background:transparent; "
                    f"font-size:10px; font-weight:600;"
                )
            if self._bar is not None:
                fill = (
                    C["dim"]
                    if self._remaining is None
                    else _rem_color(self._remaining)
                )
                self._bar._track.setStyleSheet(
                    f"#PaceTrack {{ background:{C['track']}; border:1px solid {C['border']}; "
                    f"border-radius:3px; }}"
                )
                self._bar._fill.setStyleSheet(
                    f"#PaceFill {{ background:{fill}; border:none; border-radius:3px; }}"
                )


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
                height=12,
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


def _fmt_tokens_short(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _padded_daily(cost: CostView, days: int = 30) -> list:
    """Pad last N calendar days so the chart reads continuous like official."""
    from datetime import date, timedelta

    by = {d.date: d.total_cost for d in cost.daily}
    end = date.today()
    out = []
    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        out.append((d, float(by.get(d, 0.0))))
    return out


class _CostChart(QWidget):
    """30-day spend sparkline (official CodexBar history bars)."""

    def __init__(
        self,
        cost: CostView,
        *,
        bar_color: Optional[str] = None,
        compact: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._cost = cost
        self._bar_color = bar_color or C["bar"]
        self._compact = compact
        self.setMinimumHeight(56 if compact else 72)
        self.setMaximumHeight(64 if compact else 86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if cost.daily:
            peak = max((d.total_cost for d in cost.daily), default=0.0)
            tip = (
                f"Est. {cost.history_days}d: ${cost.period_cost:,.2f}"
                f" · peak day ${peak:,.2f}"
            )
            self.setToolTip(tip)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        days = _padded_daily(self._cost, min(30, max(7, self._cost.history_days or 30)))
        if not any(c > 0 for _, c in days) and not self._cost.daily:
            p.setPen(QColor(C["dim"]))
            p.setFont(QFont("Sans", 9))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No cost history")
            p.end()
            return
        peak = max((c for _, c in days), default=0.0) or 1.0
        n = len(days)
        pad_x = 2.0
        pad_top = 4.0
        pad_bot = 4.0
        gap = 1.5
        usable = w - pad_x * 2
        bar_w = max(2.0, (usable - gap * (n - 1)) / max(n, 1))
        x = pad_x
        base_y = h - pad_bot
        max_h = base_y - pad_top
        for _, cost in days:
            if cost <= 0:
                # tiny baseline tick so empty days still read as a track
                bh = 1.5
                p.setBrush(QColor(C["track"]))
            else:
                bh = max(3.0, max_h * (cost / peak))
                p.setBrush(QColor(self._bar_color))
            p.drawRoundedRect(QRectF(x, base_y - bh, bar_w, bh), 1.5, 1.5)
            x += bar_w + gap
        p.end()


class _CostSection(QWidget):
    """Today / 30d metrics + history bar chart (matches official overview cards)."""

    def __init__(
        self,
        cost: CostView,
        *,
        accent: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(8)

        grid = QHBoxLayout()
        grid.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(2)
        tlab = QLabel("Today")
        tlab.setStyleSheet(
            f"color:{C['dim']}; border:none; background:transparent; font-size:10px;"
        )
        left.addWidget(tlab)
        tval = QLabel(f"${cost.today_cost:,.2f}")
        tval.setStyleSheet(
            f"color:{C['text']}; border:none; background:transparent; "
            f"font-size:15px; font-weight:700;"
        )
        left.addWidget(tval)
        ttok = QLabel(f"{_fmt_tokens_short(cost.today_tokens)} tokens")
        ttok.setStyleSheet(
            f"color:{C['muted']}; border:none; background:transparent; font-size:10px;"
        )
        left.addWidget(ttok)
        grid.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(2)
        plab = QLabel(f"Last {cost.history_days} days")
        plab.setStyleSheet(
            f"color:{C['dim']}; border:none; background:transparent; font-size:10px;"
        )
        right.addWidget(plab)
        pval = QLabel(f"${cost.period_cost:,.2f}")
        pval.setStyleSheet(
            f"color:{C['text']}; border:none; background:transparent; "
            f"font-size:15px; font-weight:700;"
        )
        right.addWidget(pval)
        ptok = QLabel(f"{_fmt_tokens_short(cost.period_tokens)} tokens")
        ptok.setStyleSheet(
            f"color:{C['muted']}; border:none; background:transparent; font-size:10px;"
        )
        right.addWidget(ptok)
        grid.addLayout(right, 1)
        root.addLayout(grid)

        if cost.daily or cost.period_cost > 0:
            root.addWidget(
                _CostChart(cost, bar_color=accent or C["bar"], compact=True)
            )


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
        # Clean dual-bar meter (no digit badge — % is in the meter rows)
        if view.ok and (view.primary or view.secondary):
            icon = QLabel()
            icon.setPixmap(
                paint_dual_window_pixmap(
                    primary_remaining=(
                        view.primary.remaining_percent if view.primary else None
                    ),
                    secondary_remaining=(
                        view.secondary.remaining_percent if view.secondary else None
                    ),
                    size=32,
                    credits_remaining=view.credits_remaining,
                    show_percent=False,
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
            # Still show cost if we have it (official keeps chart when usage fails)
            if cost is not None and not cost.error and (
                cost.daily or cost.period_cost > 0 or cost.today_tokens > 0
            ):
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
        root.addSpacing(4)
        accent = _PROVIDER_ACCENT.get(cost.provider.lower(), C["bar"])
        root.addWidget(_CostSection(cost, accent=accent))


class _OverviewRow(QFrame):
    """Overview card: Session 5h bar + cost history chart (official layout)."""

    def __init__(
        self,
        view: ProviderView,
        on_open,
        cost: Optional[CostView] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("OverviewRow")
        accent = _PROVIDER_ACCENT.get(view.provider.lower(), C["accent"])
        self.setStyleSheet(
            f"#OverviewRow {{"
            f"  background:{C['card']}; border:1px solid {C['border']};"
            f"  border-radius:14px;"
            f"}}"
            f"#OverviewRow:hover {{ border-color:{accent}; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(view.display_name)
        name.setStyleSheet(
            f"color:{C['text']}; border:none; background:transparent; "
            f"font-size:14px; font-weight:700;"
        )
        head.addWidget(name)
        if view.plan_label:
            plan = QLabel(view.plan_label)
            plan.setStyleSheet(
                f"color:{C['accent2']}; border:none; background:transparent; "
                f"font-size:11px; font-weight:600;"
            )
            head.addWidget(plan)
        head.addStretch()
        if view.account:
            acc = QLabel(view.account)
            acc.setStyleSheet(
                f"color:{C['dim']}; border:none; background:transparent; font-size:10px;"
            )
            head.addWidget(acc)
        open_btn = QPushButton("›")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setFixedSize(28, 28)
        open_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background:{C['card2']}; color:{C['muted']}; border:none;"
            f"  border-radius:8px; font-size:16px; font-weight:600;"
            f"}}"
            f"QPushButton:hover {{ background:{C['border']}; color:{C['text']}; }}"
        )
        open_btn.clicked.connect(on_open)
        head.addWidget(open_btn)
        root.addLayout(head)

        if view.ok and view.primary is not None:
            sess = view.primary
            rem = sess.remaining_percent
            color = accent if rem > 50 else _rem_color(rem)
            meta = QHBoxLayout()
            lab = QLabel("Session (5h)")
            lab.setStyleSheet(
                f"color:{C['muted']}; border:none; background:transparent; font-size:11px;"
            )
            meta.addWidget(lab)
            meta.addStretch()
            if sess.resets_in:
                rs = QLabel(sess.resets_in)
                rs.setStyleSheet(
                    f"color:{C['dim']}; border:none; background:transparent; font-size:10px;"
                )
                meta.addWidget(rs)
            root.addLayout(meta)
            root.addWidget(
                _PaceBar(
                    remaining=rem,
                    expected_used=(
                        sess.pace.expected_used_percent if sess.pace else None
                    ),
                    color=color,
                    height=14,
                )
            )
            foot = QHBoxLayout()
            pct = QLabel(f"{int(round(rem))}% left")
            pct.setStyleSheet(
                f"color:{color}; border:none; background:transparent; "
                f"font-size:12px; font-weight:600;"
            )
            foot.addWidget(pct)
            if sess.pace is not None:
                st = sess.pace.status
                if st == "reserve":
                    pace_txt = f"{int(round(sess.pace.reserve_percent))}% in reserve"
                    pc = C["good"]
                elif st == "deficit":
                    pace_txt = f"{int(round(-sess.pace.reserve_percent))}% over pace"
                    pc = C["warn"]
                else:
                    pace_txt = "On pace"
                    pc = C["muted"]
                pl = QLabel(pace_txt)
                pl.setStyleSheet(
                    f"color:{pc}; border:none; background:transparent; "
                    f"font-size:11px; font-weight:600;"
                )
                foot.addWidget(pl)
            foot.addStretch()
            root.addLayout(foot)
        else:
            err = QLabel(view.error or "Unavailable")
            err.setWordWrap(True)
            err.setStyleSheet(
                f"color:{C['bad']}; border:none; background:transparent; font-size:11px;"
            )
            root.addWidget(err)

        # Cost history even when usage OAuth fails (official keeps chart visible)
        if cost is not None and not cost.error and (
            cost.daily or cost.period_cost > 0 or cost.today_tokens > 0
        ):
            root.addWidget(_CostSection(cost, accent=accent))


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


def _is_wayland() -> bool:
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    app = QApplication.instance()
    if app is not None and "wayland" in app.platformName().lower():
        return True
    return False


class UsagePopover(QWidget):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        web_url: Optional[str] = None,
    ) -> None:
        # Tool + frameless: works as a tray popover under X11/XWayland.
        # Pure Wayland Popup without a parent fails to map (see __main__ xcb prefer).
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("CodexBarPopover")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Shadow effects break mouse hit-testing on Wayland — do not use.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._host = host
        self._port = port
        self._web_url = web_url
        self._views: List[ProviderView] = []
        self._costs: Dict[str, CostView] = {}
        self._active: Optional[str] = None
        self._worker: Optional[_ReloadWorker] = None
        self._tab_buttons: Dict[str, _TabChip] = {}
        self._settings_open = False
        self._hide_armed = False
        self._last_anchor: Optional[QRect] = None
        self._pin_top_left: Optional[QPoint] = None  # keep corner after resize (Wayland)

        # Single continuous surface — avoids black voids between scroll/chrome
        self.setStyleSheet(
            f"#CodexBarPopover {{"
            f"  background: {C['surface']};"
            f"  border: 1px solid {C['border']};"
            f"  border-radius: 16px;"
            f"}}"
            f"QLabel {{ color: {C['text']}; background: transparent; }}"
            f"QScrollArea {{ background: {C['surface']}; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {C['surface']}; }}"
            f"QScrollBar:vertical {{ width: 8px; background: {C['surface']}; margin: 2px; }}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {C['border']}; border-radius: 4px; min-height: 24px;"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
            f"  background: {C['surface']};"
            f"}}"
            f"QPushButton {{ outline: none; }}"
        )
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(C["surface"]))
        self.setPalette(pal)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Pill tab track
        self._tab_wrap = QFrame()
        self._tab_wrap.setObjectName("TabTrack")
        self._tab_wrap.setStyleSheet(
            f"#TabTrack {{"
            f"  background: {C['surface']};"
            f"  border: none;"
            f"  border-top-left-radius: 16px; border-top-right-radius: 16px;"
            f"}}"
        )
        tab_outer = QVBoxLayout(self._tab_wrap)
        tab_outer.setContentsMargins(12, 12, 12, 8)
        self._tab_track = QFrame()
        self._tab_track.setObjectName("PillTrack")
        self._tab_track.setStyleSheet(
            f"#PillTrack {{"
            f"  background: {C['card']}; border: 1px solid {C['border']};"
            f"  border-radius: 11px;"
            f"}}"
        )
        self._tabs = QHBoxLayout(self._tab_track)
        self._tabs.setContentsMargins(4, 4, 4, 4)
        self._tabs.setSpacing(4)
        self._tabs.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # Room for uniform 48px chips (label + mini bar)
        self._tab_track.setMinimumHeight(_TabChip.TAB_H + 8)
        tab_outer.addWidget(self._tab_track)
        outer.addWidget(self._tab_wrap, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setAutoFillBackground(True)
        self._scroll.viewport().setAutoFillBackground(True)
        sp = self._scroll.palette()
        sp.setColor(self._scroll.backgroundRole(), QColor(C["surface"]))
        self._scroll.setPalette(sp)
        self._scroll.viewport().setPalette(sp)
        self._scroll.viewport().setStyleSheet(f"background: {C['surface']};")
        self._body = QWidget()
        self._body.setAutoFillBackground(True)
        self._body.setStyleSheet(f"background: {C['surface']};")
        bp = self._body.palette()
        bp.setColor(self._body.backgroundRole(), QColor(C["surface"]))
        self._body.setPalette(bp)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 8, 14, 12)
        self._body_layout.setSpacing(10)
        self._body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._body)
        self._scroll.setMinimumWidth(400)
        # stretch=0 so scroll does not eat infinite empty black space
        outer.addWidget(self._scroll, 1)

        # Menu footer
        self._foot = QFrame()
        self._foot.setObjectName("Footer")
        self._foot.setStyleSheet(
            f"#Footer {{"
            f"  background: {C['card']};"
            f"  border-top: 1px solid {C['border']};"
            f"  border-bottom-left-radius: 16px; border-bottom-right-radius: 16px;"
            f"}}"
        )
        actions = QVBoxLayout(self._foot)
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
        outer.addWidget(self._foot, 0)

        self._set_web_url(web_url)
        self.setMinimumWidth(400)
        self.setMinimumHeight(280)
        self.resize(420, 520)

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
        """Back-compat: open at current pointer / panel corner."""
        self.show_at_tray(None, click_pos=QCursor.pos())

    def show_at_tray(
        self,
        tray: Optional[QSystemTrayIcon] = None,
        click_pos: Optional[QPoint] = None,
    ) -> None:
        """Open once under tray; later reloads only grow height (no re-dock / no drift)."""
        raw = QPoint(click_pos) if click_pos is not None else QCursor.pos()
        # StatusNotifier clicks often report (0,0) — ignore those
        pos = None if (raw.x() <= 0 and raw.y() <= 0) else raw

        if len(self._views) > 1:
            self._active = "overview"

        w = 420
        # Use a modest height only to decide below/above once — not final size
        probe_h = 360

        anchor = self._tray_anchor_rect(tray, pos)
        self._last_anchor = QRect(anchor)
        x, y = self._compute_pos(anchor, w, probe_h)
        # Lock top-left for the lifetime of this open session
        self._pin_top_left = QPoint(x, y)

        self.setGeometry(x, y, w, probe_h)
        self.show()
        self.move(x, y)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            logger.info(
                "popover show pin=%s anchor=%s click=%s full=%s avail=%s",
                self._pin_top_left,
                anchor,
                pos,
                screen.geometry(),
                screen.availableGeometry(),
            )
        self.reload()

    @staticmethod
    def _tray_anchor_rect(
        tray: Optional[QSystemTrayIcon],
        click: Optional[QPoint],
    ) -> QRect:
        """Resolve a rect to hang the popover under.

        On KDE + StatusNotifier, ``tray.geometry()`` is usually empty and
        ``QCursor.pos()`` at activate is often a *stale* pointer (y not on the
        panel). Trust click **x** for horizontal, but pin **y** to the panel
        edge so the window sits under the icon strip — not mid-screen.
        """
        if tray is not None:
            try:
                g = tray.geometry()
                if (
                    g.isValid()
                    and g.width() > 2
                    and g.height() > 2
                    and g.width() < 400
                    and (g.x() > 0 or g.y() > 0)
                ):
                    return QRect(g)
            except Exception:
                pass

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            if click is not None:
                return QRect(click.x() - 12, click.y() - 12, 24, 24)
            return QRect(100, 40, 24, 24)

        full = screen.geometry()
        avail = screen.availableGeometry()
        # Horizontal: prefer click x (user said left/right is about right)
        if click is not None and click.x() > 0:
            cx = click.x()
        else:
            cx = avail.right() - 20

        # Vertical: always the panel strip — never stale cursor y (often ~200px mid-screen)
        panel_top = avail.top() - full.top()
        panel_bot = full.bottom() - avail.bottom()
        if panel_top >= 8:
            # Top panel reserves space; hang at first pixel of free area
            return QRect(cx - 12, avail.top(), 24, 1)
        if panel_bot >= 8:
            return QRect(cx - 12, avail.bottom() - 1, 24, 1)

        # No strut (common on Wayland/XWayland): assume Plasma top panel ~40px
        # and only treat click.y as panel if it is actually near the edge.
        assumed = 40
        if click is not None and click.y() > full.bottom() - 80:
            return QRect(cx - 12, full.bottom() - assumed, 24, 1)
        return QRect(cx - 12, full.top() + assumed, 24, 1)

    def _compute_pos(self, anchor: QRect, w: int, h: int) -> tuple[int, int]:
        """One-shot: y flush under top panel (or above bottom); x near tray."""
        screen = (
            QGuiApplication.screenAt(QPoint(anchor.center().x(), anchor.center().y()))
            or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return max(0, anchor.center().x() - w // 2), max(0, anchor.bottom() + 4)
        avail = screen.availableGeometry()
        full = screen.geometry()
        gap = 2

        # Horizontal near tray/icon
        x = anchor.center().x() - w // 2
        if anchor.center().x() > avail.left() + avail.width() * 0.55:
            x = min(anchor.right() + 4, avail.right() - 6) - w
        x = max(avail.left() + 6, min(x, avail.right() - w - 6))

        panel_top = avail.top() - full.top()
        panel_bot = full.bottom() - avail.bottom()

        if panel_top >= 8:
            # Flush under top panel
            y = avail.top() + gap
            return int(x), int(y)
        if panel_bot >= 8:
            y = avail.bottom() - h - gap
            return int(x), int(max(avail.top() + gap, y))

        # No strut: anchor.top() is already "under assumed panel"
        y = anchor.top() + gap
        # Bottom-tray case: anchor near bottom
        if anchor.top() > full.center().y():
            y = anchor.top() - h - gap
            y = max(full.top() + gap, y)
        else:
            y = min(y, full.bottom() - h - gap)
            y = max(full.top() + 36, y)  # never cover assumed panel
        return int(x), int(y)

    def _apply_pinned_geometry(self, width: int, height: int) -> None:
        """Resize in place — never recompute anchor (prevents visual drift)."""
        pin = self._pin_top_left
        if pin is None:
            self.resize(width, height)
            return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            # Clamp height so bottom stays on-screen; keep top pinned
            max_h = max(200, avail.bottom() - pin.y() - 8)
            height = min(height, max_h)
            # Keep right edge in bounds if width changes
            x = pin.x()
            if x + width > avail.right() - 6:
                x = avail.right() - width - 6
            x = max(avail.left() + 6, x)
            pin = QPoint(x, pin.y())
            self._pin_top_left = pin
        self.setGeometry(pin.x(), pin.y(), width, height)

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
            chip = _TabChip("Overview", accent=C["accent"], show_bar=False)
            chip.clicked.connect(lambda: self._select_tab("overview"))
            self._tab_buttons["overview"] = chip
            self._tabs.addWidget(chip, 1)
        for v in self._views:
            rem: Optional[float] = None
            exp: Optional[float] = None
            if v.ok and v.primary is not None:
                rem = v.primary.remaining_percent
                if v.primary.pace is not None:
                    exp = v.primary.pace.expected_used_percent
            chip = _TabChip(
                v.display_name,
                accent=_PROVIDER_ACCENT.get(v.provider.lower(), C["accent"]),
                remaining=rem,
                expected_used=exp,
                show_bar=True,
            )
            chip.clicked.connect(lambda p=v.provider: self._select_tab(p))
            self._tab_buttons[v.provider] = chip
            self._tabs.addWidget(chip, 1)
        self._paint_tabs()

    def _select_tab(self, key: str) -> None:
        self._active = key
        self._paint_tabs()
        self._rebuild_body()
        # Keep focus so focusOut does not dismiss mid-click on Wayland
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _paint_tabs(self) -> None:
        for k, chip in self._tab_buttons.items():
            chip.set_active(k == self._active)

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
            self._fit_height()
            return

        if self._active == "overview":
            mb = load_menu_bar_settings()
            for v in order_overview_views(self._views, mb):
                self._body_layout.addWidget(
                    _OverviewRow(
                        v,
                        on_open=lambda p=v.provider: self._select_tab(p),
                        cost=self._costs.get(v.provider),
                    )
                )
        else:
            view = next(
                (v for v in self._views if v.provider == self._active),
                self._views[0],
            )
            cost = self._costs.get(view.provider)
            self._body_layout.addWidget(_ProviderCard(view, cost=cost))

        # No addStretch() — with setWidgetResizable it paints a tall black void.

        ok_n = sum(1 for v in self._views if v.ok)
        self._status.setText(
            f"{ok_n}/{len(self._views)} providers · official CLI"
            + (f" · web {self._web_url.replace('http://', '')}" if self._web_url else "")
        )
        self._fit_height()

    def _fit_height(self) -> None:
        """Size window to content; scroll only when taller than screen budget."""
        QApplication.processEvents()
        self._body.adjustSize()
        content_h = max(
            self._body.sizeHint().height(),
            self._body_layout.sizeHint().height(),
            80,
        )
        # Chrome: tabs + footer measured when available
        tab_h = self._tab_wrap.sizeHint().height() if hasattr(self, "_tab_wrap") else 56
        foot_h = self._foot.sizeHint().height() if hasattr(self, "_foot") else 150
        if tab_h < 40:
            tab_h = 56
        if foot_h < 80:
            foot_h = 150

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry().height() if screen else 900
        # Leave room for panel margins on Plasma
        max_total = max(360, int(avail * 0.88))
        chrome = tab_h + foot_h + 8
        max_scroll = max(160, max_total - chrome)

        # Prefer full content height when it fits; otherwise scroll.
        scroll_h = min(content_h + 8, max_scroll)
        # Ensure enough room for card + cost chart
        scroll_h = max(scroll_h, min(content_h + 8, max_scroll))
        if content_h > max_scroll:
            scroll_h = max_scroll
        else:
            # Tight fit — no empty void below last card
            scroll_h = content_h + 12

        self._scroll.setMinimumHeight(min(scroll_h, max_scroll))
        self._scroll.setMaximumHeight(max_scroll)
        self._scroll.setFixedHeight(min(scroll_h, max_scroll))

        total = chrome + min(scroll_h, max_scroll)
        total = max(280, min(total, max_total))
        width = max(420, min(self.width() if self.width() > 200 else 420, 480))
        if self.isVisible() and self._pin_top_left is not None:
            # Grow/shrink height only — top-left stays put (no re-dock, no drift)
            self._apply_pinned_geometry(width, total)
        else:
            self.resize(width, total)
        self._body.updateGeometry()
        self.updateGeometry()

    def _open_settings(self) -> None:
        from codexbar_gui.config_dialog import ConfigDialog

        self._settings_open = True
        try:
            # Parent=None so modal dialog is not a child that traps popover focus chaos
            dlg = ConfigDialog(self._host, self._port, parent=None)
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
            dlg.exec()
        finally:
            self._settings_open = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.reload()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        # Debounced outside-click dismiss — never hide while interacting with self/dialogs
        if not self._hide_armed:
            self._hide_armed = True
            QTimer.singleShot(220, self._maybe_hide)
        super().focusOutEvent(event)

    def _maybe_hide(self) -> None:
        self._hide_armed = False
        if not self.isVisible() or self._settings_open:
            return
        app = QApplication.instance()
        if app is None:
            return
        if app.activeModalWidget() is not None:
            return
        active = app.activeWindow()
        if active is self:
            return
        # Click landed on our widget tree (tabs/buttons often steal focus first)
        w = app.widgetAt(QCursor.pos())
        if w is not None and (w is self or self.isAncestorOf(w)):
            return
        if self.underMouse():
            return
        self.hide()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
