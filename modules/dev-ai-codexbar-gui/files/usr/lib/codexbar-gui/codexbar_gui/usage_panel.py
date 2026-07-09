"""Usage panel — right-click context menu for the system tray icon.

Displays usage data for all configured providers as a ``QMenu`` with:

- Provider name + status icon (enabled/disabled)
- Progress bar showing usage percentage
- Color coding: green (<50%), yellow (50-80%), red (>80%)
- Reset countdown description
- Expand/collapse toggle for detailed information
- Separator and action items (refresh, config, quit)

The panel fetches data from the ``aipc-usage`` HTTP server and renders
a fresh menu on every open (QMenu doesn't persist well between opens).
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMenu,
    QWidgetAction,
    QWidget,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSpacerItem,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QPixmap

from codexbar_gui.icon_updater import generate_svg, svg_to_qicon_data
from codexbar_gui.server_launcher import check_server

logger = logging.getLogger("codexbar_gui.usage_panel")


_USAGE_BAR_WIDTH = 120
_PROGRESS_HEIGHT = 16
_ROW_HEIGHT = 32


class ProviderRow(QWidget):
    """A single provider row in the usage panel menu.

    Layout (horizontal):
      [icon] [name]  [progress bar] [percent]  [status]
    """

    def __init__(
        self,
        provider_id: str,
        snapshot: Optional[Dict[str, Any]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._provider_id = provider_id
        self._snapshot = snapshot or {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        # Status icon (left)
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(_ROW_HEIGHT - 4, _ROW_HEIGHT - 4)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(self._icon_label)

        # Provider name
        self._name_label = QLabel()
        self._name_label.setFont(QFont("Sans", 9))
        self._name_label.setFixedWidth(110)
        self._name_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._name_label)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(_PROGRESS_HEIGHT)
        self._progress_bar.setFixedWidth(_USAGE_BAR_WIDTH)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFormat("")
        layout.addWidget(self._progress_bar)

        # Percentage label
        self._percent_label = QLabel()
        self._percent_label.setFont(QFont("Sans", 8))
        self._percent_label.setFixedWidth(40)
        self._percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._percent_label)

        # Spacer to push status to the right
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding))

        # Status label
        self._status_label = QLabel()
        self._status_label.setFont(QFont("Sans", 8))
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._status_label)

    def update_data(
        self,
        snapshot: Optional[Dict[str, Any]],
        error: bool = False,
    ) -> None:
        """Refresh the row with new usage data."""
        self._snapshot = snapshot or {}

        # Display name from snapshot or provider ID
        display = (
            self._snapshot.get("display_name")
            or self._snapshot.get("provider_name")
            or self._provider_id.title()
        )
        self._name_label.setText(display)

        # Usage percentage
        primary = self._snapshot.get("primary") or {}
        used_pct = primary.get("used_percent", 0)
        if used_pct is None:
            used_pct = 0
        used_pct = max(0, min(100, int(used_pct)))

        self._progress_bar.setValue(used_pct)
        self._percent_label.setText(f"{used_pct}%")

        # Color coding
        if error:
            self._set_colors("#e74c3c", "#e74c3c")
            self._status_label.setText("error")
            self._status_label.setStyleSheet("color: #e74c3c;")
        elif used_pct > 80:
            self._set_colors("#e74c3c", "#e74c3c")
            self._status_label.setText("high")
            self._status_label.setStyleSheet("color: #e74c3c;")
        elif used_pct > 50:
            self._set_colors("#f39c12", "#f39c12")
            self._status_label.setText("medium")
            self._status_label.setStyleSheet("color: #f39c12;")
        else:
            self._set_colors("#27ae60", "#27ae60")
            self._status_label.setText("ok")
            self._status_label.setStyleSheet("color: #27ae60;")

        # Reset description overrides status text
        reset_desc = primary.get("reset_description") or ""
        if reset_desc and not error:
            self._status_label.setText(reset_desc)

        # Status from snapshot overrides color coding
        status = self._snapshot.get("status")
        if status == "no-api-key":
            self._set_colors("#95a5a6", "#95a5a6")
            self._status_label.setText("no key")
            self._status_label.setStyleSheet("color: #95a5a6;")
        elif status == "error":
            self._set_colors("#e74c3c", "#e74c3c")
            self._status_label.setText("error")
            self._status_label.setStyleSheet("color: #e74c3c;")

        # Generate status icon
        self._update_icon(error, used_pct)

    def _set_colors(self, bar_color: str, text_color: str) -> None:
        self._progress_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {bar_color}; border-radius: 2px; }}"
            f"QProgressBar {{ border: none; background: #34495e; }}"
        )
        self._percent_label.setStyleSheet(f"color: {text_color};")

    def _update_icon(self, error: bool, percent: int) -> None:
        try:
            if error:
                svg = generate_svg(percent=None, error=True)
            elif percent >= 100:
                svg = generate_svg(percent=100, error=False)
            else:
                svg = generate_svg(percent=percent, error=False)
            data_uri = svg_to_qicon_data(svg)
            pixmap = QPixmap()
            encoded = data_uri.encode("utf-8") if isinstance(data_uri, str) else data_uri
            if not pixmap.loadFromData(encoded):
                raise ValueError("loadFromData failed")
            scaled = pixmap.scaled(
                _ROW_HEIGHT - 4, _ROW_HEIGHT - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._icon_label.setPixmap(scaled)
        except Exception:
            self._icon_label.setText("\u25cf")
            self._icon_label.setStyleSheet("color: #95a5a6; font-size: 12px;")


class UsagePanel(QMenu):
    """Right-click context menu showing provider usage data.

    The panel fetches fresh data from the usage server on every open,
    so the displayed data is always current (up to the refresh interval).
    """

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
        self._provider_rows: List[ProviderRow] = []
        self._data: List[Dict[str, Any]] = []

        self._build_menu()

    def _build_menu(self) -> None:
        """Build the menu structure."""
        self.setWindowTitle("CodexBar")

        # Separator
        self.addSeparator()

        # Header label
        header = QWidgetAction(self)
        header.setDefaultWidget(QLabel("<b>CodexBar — AI Usage Tracker</b>"))
        self.addAction(header)

        self.addSeparator()

        # Initial data fetch (deferred to next event loop iteration)
        QTimer.singleShot(0, self._refresh_data)

        # Expand/collapse toggle
        self._expand_action = QAction("Show details \u25bc", self)
        self._expand_action.setCheckable(True)
        self._expand_action.setChecked(False)
        self._expand_action.triggered.connect(self._toggle_expand)
        self.addAction(self._expand_action)

        self.addSeparator()

        # Actions
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self._refresh_data)
        self.addAction(refresh_action)

        config_action = QAction("Settings...", self)
        config_action.triggered.connect(self._open_config)
        self.addAction(config_action)

        self.addSeparator()

        quit_action = QAction("Quit CodexBar", self)
        quit_action.triggered.connect(self._quit_app)
        self.addAction(quit_action)

    def _refresh_data(self) -> None:
        """Fetch fresh usage data from the HTTP server."""
        url = f"http://{self._host}:{self._port}/usage"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8")
                new_data = json.loads(body)

            self._data = new_data
            logger.debug("Fetched %d provider snapshots", len(new_data))

            # Update or recreate rows
            if not self._provider_rows:
                self._clear_rows()
                if new_data:
                    for item in new_data:
                        provider_id = item.get("provider", "unknown")
                        snapshot = item.get("snapshot", {})
                        row = ProviderRow(provider_id, snapshot)
                        self._provider_rows.append(row)
                        action = QWidgetAction(self)
                        action.setDefaultWidget(row)
                        self.insertAction(self._expand_action, action)
            else:
                for i, row in enumerate(self._provider_rows):
                    if i < len(new_data):
                        item = new_data[i]
                        snapshot = item.get("snapshot", {})
                        row.update_data(snapshot)

        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning("Failed to fetch usage data: %s", e)
            self._data = []

            # Show "no data" placeholder
            if not self._provider_rows:
                no_data_action = self.addAction("No data — server may not be running")
                no_data_action.setEnabled(False)

    def _clear_rows(self) -> None:
        """Remove all provider row actions from the menu."""
        # Find and remove actions before the expand action
        actions = self.actions()
        to_remove = []
        for action in actions:
            if action is self._expand_action:
                break
            to_remove.append(action)
        for action in to_remove:
            self.removeAction(action)
        self._provider_rows.clear()

    def _toggle_expand(self, checked: bool) -> None:
        """Toggle detailed information visibility."""
        self._expanded = checked
        if checked:
            logger.debug("Expanding provider details")
        else:
            logger.debug("Collapsing provider details")

    def _open_config(self) -> None:
        """Open the configuration dialog."""
        from codexbar_gui.config_dialog import ConfigDialog
        dialog = ConfigDialog(self._host, self._port)
        dialog.exec()

    def _quit_app(self) -> None:
        """Quit the application."""
        from PySide6.QtWidgets import QApplication
        QApplication.quit()


def fetch_usage_data(host: str = "127.0.0.1", port: int = 8080) -> List[Dict[str, Any]]:
    """Fetch usage data from the HTTP server.

    Args:
        host: Server hostname.
        port: Server port.

    Returns:
        List of usage snapshots, one per provider.
    """
    url = f"http://{host}:{port}/usage"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as e:
        logger.debug("fetch_usage_data failed: %s", e)
        return []


def fetch_server_health(host: str = "127.0.0.1", port: int = 8080) -> bool:
    """Check if the server is healthy."""
    return check_server(host, port)
