"""Right-click context menu for the CodexBar tray icon."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QSizePolicy,
    QSpacerItem,
    QWidget,
    QWidgetAction,
)

from codexbar_gui.icon_updater import paint_usage_pixmap
from codexbar_gui.server_launcher import check_server

logger = logging.getLogger("codexbar_gui.usage_panel")

_USAGE_BAR_WIDTH = 120
_PROGRESS_HEIGHT = 14
_ROW_HEIGHT = 30


def _normalize_pct(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    # Accept 0–1 fractions as well as 0–100.
    if 0.0 <= val <= 2.0:
        val *= 100.0
    return max(0.0, min(100.0, val))


def _snapshot_of(item: Dict[str, Any]) -> Dict[str, Any]:
    snap = item.get("snapshot")
    if isinstance(snap, dict):
        return snap
    return item


class ProviderRow(QWidget):
    """One provider line: name | bar | % | status/reset."""

    def __init__(
        self,
        provider_id: str,
        snapshot: Optional[Dict[str, Any]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._provider_id = provider_id
        self._snapshot: Dict[str, Any] = snapshot or {}
        self._init_ui()
        self.update_data(self._snapshot)

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(_ROW_HEIGHT - 4, _ROW_HEIGHT - 4)
        layout.addWidget(self._icon_label)

        self._name_label = QLabel()
        self._name_label.setFont(QFont("Sans", 9))
        self._name_label.setFixedWidth(100)
        layout.addWidget(self._name_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(_PROGRESS_HEIGHT)
        self._progress_bar.setFixedWidth(_USAGE_BAR_WIDTH)
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)

        self._percent_label = QLabel()
        self._percent_label.setFont(QFont("Sans", 8))
        self._percent_label.setFixedWidth(40)
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._percent_label)

        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding))

        self._status_label = QLabel()
        self._status_label.setFont(QFont("Sans", 8))
        self._status_label.setMinimumWidth(72)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._status_label)

    def update_data(self, snapshot: Optional[Dict[str, Any]], error: bool = False) -> None:
        self._snapshot = snapshot or {}
        display = (
            self._snapshot.get("display_name")
            or self._snapshot.get("provider_name")
            or self._provider_id
        )
        self._name_label.setText(str(display))

        primary = self._snapshot.get("primary") or {}
        used = _normalize_pct(primary.get("used_percent"))
        status = self._snapshot.get("status") or ""
        is_error = error or status == "error"

        if used is None:
            self._progress_bar.setValue(0)
            self._percent_label.setText("—")
            color = "#95a5a6"
        else:
            self._progress_bar.setValue(int(used))
            self._percent_label.setText(f"{int(used)}%")
            if used > 80:
                color = "#e74c3c"
            elif used > 50:
                color = "#f39c12"
            else:
                color = "#27ae60"

        if is_error:
            color = "#e74c3c"
            label = "error"
        elif status == "no-api-key":
            color = "#95a5a6"
            label = "no key"
        elif status in {"not-configured", "not-implemented"}:
            color = "#95a5a6"
            label = status.replace("-", " ")
        elif status == "ok" or used is not None:
            reset = primary.get("reset_description") or ""
            label = reset if reset else (status or "ok")
        else:
            label = status or "—"

        self._set_colors(color)
        self._status_label.setText(str(label)[:28])
        self._status_label.setStyleSheet(f"color: {color};")
        self._status_label.setToolTip(str(self._snapshot.get("error") or label))

        pm = paint_usage_pixmap(percent=used, error=is_error, size=_ROW_HEIGHT - 4)
        self._icon_label.setPixmap(pm)

    def _set_colors(self, bar_color: str) -> None:
        self._progress_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {bar_color}; border-radius: 2px; }}"
            f"QProgressBar {{ border: none; background: #34495e; border-radius: 2px; }}"
        )
        self._percent_label.setStyleSheet(f"color: {bar_color};")


class UsagePanel(QMenu):
    """Tray context menu; rebuilds provider rows on each aboutToShow."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        parent: Optional[QMenu] = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._expanded = False
        self._data: List[Dict[str, Any]] = []
        self._row_actions: List[QWidgetAction] = []
        self._detail_actions: List[QAction] = []
        self._placeholder_action: Optional[QAction] = None

        self.setTitle("CodexBar")
        self.aboutToShow.connect(self._on_about_to_show)

        header = QWidgetAction(self)
        header.setDefaultWidget(QLabel("<b>CodexBar — AI usage</b>"))
        self.addAction(header)
        self.addSeparator()

        # Insertion point for provider rows (before expand).
        self._expand_action = QAction("Show details ▾", self)
        self._expand_action.setCheckable(True)
        self._expand_action.toggled.connect(self._toggle_expand)
        self.addAction(self._expand_action)
        self.addSeparator()

        refresh = QAction("Refresh", self)
        refresh.triggered.connect(self._refresh_data)
        self.addAction(refresh)

        settings = QAction("Settings…", self)
        settings.triggered.connect(self._open_config)
        self.addAction(settings)

        self.addSeparator()
        quit_act = QAction("Quit CodexBar", self)
        quit_act.triggered.connect(self._quit_app)
        self.addAction(quit_act)

    def _on_about_to_show(self) -> None:
        QTimer.singleShot(0, self._refresh_data)

    def _clear_dynamic_rows(self) -> None:
        for act in self._row_actions + self._detail_actions:
            self.removeAction(act)
            act.deleteLater()
        self._row_actions.clear()
        self._detail_actions.clear()
        if self._placeholder_action is not None:
            self.removeAction(self._placeholder_action)
            self._placeholder_action.deleteLater()
            self._placeholder_action = None

    def _insert_before_expand(self, action: QAction) -> None:
        self.insertAction(self._expand_action, action)

    def _refresh_data(self) -> None:
        url = f"http://{self._host}:{self._port}/usage"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                new_data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(new_data, list):
                new_data = []
            self._data = new_data
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("usage fetch failed: %s", exc)
            self._data = []

        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        self._clear_dynamic_rows()

        if not self._data:
            msg = "No data — is the usage server running?"
            if not check_server(self._host, self._port):
                msg = f"Server down ({self._host}:{self._port})"
            self._placeholder_action = QAction(msg, self)
            self._placeholder_action.setEnabled(False)
            self._insert_before_expand(self._placeholder_action)
            return

        # Prefer interesting rows: ok / has primary / errors; de-emphasize empty stubs.
        items = list(self._data)
        items.sort(key=self._sort_key)

        for item in items:
            snap = _snapshot_of(item)
            pid = str(item.get("provider") or snap.get("provider") or "unknown")
            row = ProviderRow(pid, snap)
            row.update_data(snap)
            action = QWidgetAction(self)
            action.setDefaultWidget(row)
            self._insert_before_expand(action)
            self._row_actions.append(action)

            if self._expanded:
                detail = self._detail_text(pid, snap)
                d_act = QAction(f"    ↳ {detail}", self)
                d_act.setEnabled(False)
                self._insert_before_expand(d_act)
                self._detail_actions.append(d_act)

        self._expand_action.setText(
            "Hide details ▴" if self._expanded else "Show details ▾"
        )

    @staticmethod
    def _sort_key(item: Dict[str, Any]) -> tuple:
        snap = _snapshot_of(item)
        primary = snap.get("primary") or {}
        pct = _normalize_pct(primary.get("used_percent"))
        status = snap.get("status") or ""
        # Higher usage first; then errors; then keyed providers.
        rank = 0
        if pct is not None:
            rank = -int(pct)
        elif status == "error":
            rank = 50
        elif status == "no-api-key":
            rank = 80
        else:
            rank = 90
        return (rank, str(item.get("provider") or ""))

    @staticmethod
    def _detail_text(pid: str, snap: Dict[str, Any]) -> str:
        parts: List[str] = [pid]
        status = snap.get("status")
        if status:
            parts.append(f"status={status}")
        for key, label in (("primary", "p"), ("secondary", "s"), ("tertiary", "t")):
            win = snap.get(key)
            if not isinstance(win, dict):
                continue
            pct = _normalize_pct(win.get("used_percent"))
            reset = win.get("reset_description") or ""
            if pct is not None:
                parts.append(f"{label}={int(pct)}%")
            if reset:
                parts.append(reset)
        err = snap.get("error")
        if err:
            parts.append(str(err)[:80])
        identity = snap.get("identity") or {}
        if isinstance(identity, dict) and identity.get("account_email"):
            parts.append(str(identity["account_email"]))
        return " · ".join(parts)[:120]

    def _toggle_expand(self, checked: bool) -> None:
        self._expanded = checked
        self._rebuild_rows()

    def _open_config(self) -> None:
        from codexbar_gui.config_dialog import ConfigDialog

        dialog = ConfigDialog(self._host, self._port)
        if dialog.exec():
            self._refresh_data()

    def _quit_app(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.quit()


def fetch_usage_data(host: str = "127.0.0.1", port: int = 8080) -> List[Dict[str, Any]]:
    url = f"http://{host}:{port}/usage"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as exc:
        logger.debug("fetch_usage_data: %s", exc)
        return []


def fetch_server_health(host: str = "127.0.0.1", port: int = 8080) -> bool:
    return check_server(host, port)


def summary_from_data(data: List[Dict[str, Any]]) -> tuple[Optional[float], str]:
    """Return (max_percent_or_None, tooltip text) for the tray icon."""
    lines: List[str] = []
    max_pct: Optional[float] = None
    for item in data:
        snap = _snapshot_of(item)
        pid = item.get("provider") or snap.get("provider") or "?"
        primary = snap.get("primary") or {}
        pct = _normalize_pct(primary.get("used_percent"))
        status = snap.get("status") or ""
        if pct is not None:
            max_pct = pct if max_pct is None else max(max_pct, pct)
            lines.append(f"{pid}: {int(pct)}% ({status or 'ok'})")
        else:
            lines.append(f"{pid}: {status or '—'}")
    if not lines:
        return None, "CodexBar — no data"
    tip = "CodexBar\n" + "\n".join(lines[:12])
    if len(lines) > 12:
        tip += f"\n… +{len(lines) - 12} more"
    return max_pct, tip
