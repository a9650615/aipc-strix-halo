"""Tray menu that renders **upstream CodexBar** provider cards.

Priority UI (what macOS CodexBar actually shows):
- Session + Weekly remaining bars (not a single fake %)
- Pace summary
- Reset times
- Account / plan / credits
- Real errors from the CLI
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from codexbar_gui.icon_updater import paint_usage_pixmap
from codexbar_gui.upstream import (
    ProviderView,
    RateWindowView,
    fetch_usage_views,
    find_codexbar_binary,
    health_check,
)

logger = logging.getLogger("codexbar_gui.usage_panel")


class _WindowRow(QWidget):
    """One session/weekly line: label | remaining bar | % left | reset."""

    def __init__(self, win: RateWindowView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(6)

        name = QLabel(win.label)
        name.setFixedWidth(88)
        name.setFont(QFont("Sans", 8))
        layout.addWidget(name)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(win.remaining_percent))
        bar.setFixedHeight(12)
        bar.setFixedWidth(110)
        bar.setTextVisible(False)
        rem = win.remaining_percent
        if rem <= 20:
            color = "#e74c3c"
        elif rem <= 50:
            color = "#f39c12"
        else:
            color = "#27ae60"
        bar.setStyleSheet(
            f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}"
            f"QProgressBar {{ border:none; background:#2c3e50; border-radius:2px; }}"
        )
        layout.addWidget(bar)

        pct = QLabel(f"{int(rem)}% left")
        pct.setFixedWidth(56)
        pct.setFont(QFont("Sans", 8))
        pct.setStyleSheet(f"color:{color};")
        layout.addWidget(pct)

        reset = QLabel(win.reset_description or "")
        reset.setFont(QFont("Sans", 8))
        reset.setStyleSheet("color:#aaa;")
        reset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(reset)


class ProviderCard(QWidget):
    """Card matching official CLI summary for one provider."""

    def __init__(self, view: ProviderView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._view = view
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(3)

        head = QHBoxLayout()
        icon = QLabel()
        rem = view.headline_remaining
        icon.setPixmap(
            paint_usage_pixmap(
                percent=(100.0 - rem) if rem is not None else None,
                error=not view.ok,
                size=22,
            )
        )
        head.addWidget(icon)

        title = QLabel(f"<b>{view.display_name}</b>")
        title.setFont(QFont("Sans", 10))
        head.addWidget(title)

        if view.source:
            src = QLabel(view.source)
            src.setStyleSheet("color:#888; font-size:10px;")
            head.addWidget(src)
        head.addStretch()
        root.addLayout(head)

        if view.error:
            err = QLabel(view.error)
            err.setWordWrap(True)
            err.setStyleSheet("color:#e74c3c; font-size:11px;")
            err.setMaximumWidth(360)
            root.addWidget(err)
            return

        for win in (view.primary, view.secondary, view.tertiary):
            if win is not None:
                root.addWidget(_WindowRow(win))

        if view.pace_summary:
            pace = QLabel(view.pace_summary)
            pace.setWordWrap(True)
            pace.setStyleSheet("color:#7fdbca; font-size:10px;")
            pace.setMaximumWidth(360)
            root.addWidget(pace)

        meta_bits = []
        if view.account:
            meta_bits.append(view.account)
        if view.plan:
            meta_bits.append(f"plan:{view.plan}")
        if view.credits_remaining is not None:
            meta_bits.append(f"credits:{view.credits_remaining:g}")
        if view.version:
            meta_bits.append(f"v{view.version}")
        if meta_bits:
            meta = QLabel(" · ".join(meta_bits))
            meta.setStyleSheet("color:#999; font-size:10px;")
            root.addWidget(meta)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#333;")
        root.addWidget(line)


class UsagePanel(QMenu):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        parent: Optional[QMenu] = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._views: List[ProviderView] = []
        self._dynamic: List[QAction] = []

        self.setTitle("CodexBar")
        self.aboutToShow.connect(lambda: QTimer.singleShot(0, self.refresh))

        header = QWidgetAction(self)
        header.setDefaultWidget(QLabel("<b>CodexBar</b>  <span style='color:#888'>usage</span>"))
        self.addAction(header)
        self.addSeparator()

        self._anchor = QAction(self)  # invisible insert point before actions
        self._anchor.setVisible(False)
        self.addAction(self._anchor)

        refresh = QAction("Refresh now", self)
        refresh.triggered.connect(self.refresh)
        self.addAction(refresh)

        settings = QAction("Settings…", self)
        settings.triggered.connect(self._open_config)
        self.addAction(settings)

        self.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self._quit)
        self.addAction(quit_act)

    def refresh(self) -> None:
        # Prefer CLI for truth if official binary exists (avoids stale/wrong aipc port).
        prefer_cli = find_codexbar_binary() is not None
        try:
            self._views = fetch_usage_views(
                self._host, self._port, prefer_cli=prefer_cli
            )
        except Exception as exc:
            logger.warning("refresh failed: %s", exc)
            self._views = []
        self._rebuild()

    def _clear_dynamic(self) -> None:
        for a in self._dynamic:
            self.removeAction(a)
            a.deleteLater()
        self._dynamic.clear()

    def _rebuild(self) -> None:
        self._clear_dynamic()
        insert_before = self._anchor

        if not self._views:
            bin_ok = find_codexbar_binary()
            srv = health_check(self._host, self._port)
            msg = "No usage data."
            if not bin_ok and not srv:
                msg = "Install CodexBar CLI or start: codexbar serve"
            elif not bin_ok:
                msg = "No official codexbar binary; HTTP empty/failed"
            act = QAction(msg, self)
            act.setEnabled(False)
            self.insertAction(insert_before, act)
            self._dynamic.append(act)
            return

        for view in self._views:
            card = ProviderCard(view)
            wa = QWidgetAction(self)
            wa.setDefaultWidget(card)
            self.insertAction(insert_before, wa)
            self._dynamic.append(wa)

        # Footer: data source note
        bin_path = find_codexbar_binary() or "missing"
        note = QAction(f"Source: official CLI ({bin_path})", self)
        note.setEnabled(False)
        self.insertAction(insert_before, note)
        self._dynamic.append(note)

    def _open_config(self) -> None:
        from codexbar_gui.config_dialog import ConfigDialog

        ConfigDialog(self._host, self._port).exec()
        self.refresh()

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.quit()


def fetch_usage_data(host: str = "127.0.0.1", port: int = 8080) -> list:
    """Back-compat: raw list of dicts (prefer views via fetch_usage_views)."""
    views = fetch_usage_views(host, port, prefer_cli=True)
    return [v.raw for v in views]


def summary_from_views(views: List[ProviderView]) -> tuple[Optional[float], str]:
    """Icon uses worst remaining (lowest % left). Tooltip mirrors CLI cards."""
    lines: list[str] = []
    worst_remaining: Optional[float] = None
    for v in views:
        if v.error:
            lines.append(f"{v.display_name}: {v.error[:60]}")
            continue
        rem = v.headline_remaining
        if rem is not None:
            worst_remaining = rem if worst_remaining is None else min(worst_remaining, rem)
            p = v.primary
            s = v.secondary
            bits = [f"{v.display_name}:"]
            if p:
                bits.append(f"session {int(p.remaining_percent)}% left")
            if s:
                bits.append(f"week {int(s.remaining_percent)}% left")
            if v.pace_summary:
                bits.append(v.pace_summary.split("|")[0].strip())
            lines.append(" ".join(bits))
        else:
            lines.append(f"{v.display_name}: —")
    if not lines:
        return None, "CodexBar — no data"
    # Icon paint_usage_pixmap uses *used* percent for fill color.
    used_for_icon = None if worst_remaining is None else (100.0 - worst_remaining)
    tip = "CodexBar\n" + "\n".join(lines[:10])
    return used_for_icon, tip


def summary_from_data(data: list) -> tuple[Optional[float], str]:
    from codexbar_gui.upstream import parse_upstream_list

    return summary_from_views(parse_upstream_list(data))


def fetch_server_health(host: str = "127.0.0.1", port: int = 8080) -> bool:
    return health_check(host, port)
