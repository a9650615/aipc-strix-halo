"""Configuration dialog for CodexBar GUI settings.

Provides a Qt dialog for managing:

- Provider enable/disable toggles
- API key input fields
- Refresh interval setting
- Save/Cancel buttons

Configuration is stored at ``~/.config/codexbar/config.json`` (XDG-compliant).
The dialog reads/writes the same config file used by the ``aipc-usage`` CLI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QLineEdit,
    QSpinBox,
    QPushButton,
    QScrollArea,
    QWidget,
    QMessageBox,
    QGroupBox,
    QSizePolicy,
    QSpacerItem,
)

logger = logging.getLogger("codexbar_gui.config_dialog")


# Path to the codexbar config file (shared with aipc-usage CLI).
_CONFIG_DIR = Path.home() / ".config" / "codexbar"
_CONFIG_FILE = _CONFIG_DIR / "config.json"


class ProviderConfigWidget(QWidget):
    """A single provider configuration widget with enable toggle and API key."""

    api_key_changed = Signal(str, str)  # provider_id, new_key

    def __init__(
        self,
        provider_id: str,
        enabled: bool = True,
        api_key: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._provider_id = provider_id
        self._init_ui(enabled, api_key)

    def _init_ui(self, enabled: bool, api_key: Optional[str]) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        # Enable checkbox
        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(enabled)
        self._enabled_check.toggled.connect(self._on_toggled)
        self._enabled_check.setText(self._provider_id.title())
        layout.addWidget(self._enabled_check)

        # Provider name
        name_label = QLabel(self._provider_id)
        name_label.setFont(QFont("Sans", 9))
        name_label.setFixedWidth(100)
        name_label.setStyleSheet("color: #888;")
        layout.addWidget(name_label)

        # API key input (password echo mode)
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("Enter API key...")
        if api_key:
            self._key_input.setText(api_key)
        self._key_input.textChanged.connect(self._on_key_changed)
        self._key_input.setEnabled(enabled)
        self._key_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._key_input)

        # Spacer
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding))

    def _on_toggled(self, checked: bool) -> None:
        self._key_input.setEnabled(checked)
        if checked:
            self.api_key_changed.emit(self._provider_id, self._key_input.text())
        else:
            # Disabled: clear the key
            self.api_key_changed.emit(self._provider_id, "")

    def _on_key_changed(self, text: str) -> None:
        if self._enabled_check.isChecked():
            self.api_key_changed.emit(self._provider_id, text)

    def get_state(self) -> Dict[str, Any]:
        """Return the current state of this widget."""
        return {
            "id": self._provider_id,
            "enabled": self._enabled_check.isChecked(),
            "api_key": self._key_input.text(),
        }


class ConfigDialog(QDialog):
    """Configuration dialog for CodexBar GUI settings.

    Provides controls for:
    - Provider enable/disable toggles
    - API key input
    - Refresh interval
    - Save/Cancel buttons
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._providers: List[ProviderConfigWidget] = []
        self._config: Dict[str, Any] = {}

        self._init_ui()
        self._load_config()

    def _init_ui(self) -> None:
        self.setWindowTitle("CodexBar Settings")
        self.setMinimumSize(650, 420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        header = QLabel("Provider Configuration")
        header.setFont(QFont("Sans", 13, QFont.Weight.Bold))
        layout.addWidget(header)

        # Server info
        server_info = QLabel(f"Server: http://{self._host}:{self._port}")
        server_info.setFont(QFont("Sans", 9))
        server_info.setStyleSheet("color: #888;")
        layout.addWidget(server_info)

        # Scroll area for provider list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(280)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(4)

        self._provider_group = QGroupBox("Providers")
        provider_layout = QVBoxLayout(self._provider_group)
        provider_layout.setSpacing(4)

        scroll_layout.addWidget(self._provider_group)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        # Refresh interval
        interval_layout = QHBoxLayout()
        interval_label = QLabel("Refresh interval (seconds):")
        interval_label.setFont(QFont("Sans", 10))
        interval_layout.addWidget(interval_label)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(10, 3600)
        self._interval_spin.setValue(60)
        self._interval_spin.setSuffix(" s")
        interval_layout.addWidget(self._interval_spin)

        layout.addLayout(interval_layout)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_config)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _load_config(self) -> None:
        """Load configuration from the config file."""
        config_path = _CONFIG_FILE
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text())
                self._config = data
                logger.debug("Loaded config from %s", config_path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load config: %s", e)
                self._config = {}
        else:
            logger.debug("No config file at %s", config_path)

        # Load providers from registry or config
        providers = self._config.get("providers", [])
        if not providers:
            # Generate a default set of common providers
            providers = [
                {"id": "openai", "enabled": True},
                {"id": "claude", "enabled": True},
                {"id": "gemini", "enabled": False},
                {"id": "copilot", "enabled": False},
                {"id": "deepseek", "enabled": False},
                {"id": "openrouter", "enabled": False},
            ]

        # Create provider widgets
        self._provider_group.setLayout(QVBoxLayout())
        provider_layout = self._provider_group.layout()

        for prov in providers:
            provider_id = prov.get("id", "unknown")
            enabled = prov.get("enabled", True)
            api_key = prov.get("api_key", "")

            widget = ProviderConfigWidget(
                provider_id=provider_id,
                enabled=enabled,
                api_key=api_key,
            )
            self._providers.append(widget)
            provider_layout.addWidget(widget)

    def _save_config(self) -> None:
        """Save configuration to the config file."""
        providers = [w.get_state() for w in self._providers]

        # Preserve existing API keys for providers not in the UI
        existing_keys = {}
        for prov in self._config.get("providers", []):
            if prov.get("api_key"):
                existing_keys[prov["id"]] = prov["api_key"]

        # Merge with existing keys
        for prov in providers:
            if prov["id"] in existing_keys and not prov["api_key"]:
                prov["api_key"] = existing_keys[prov["id"]]

        config_data = {
            "version": self._config.get("version", 1),
            "providers": providers,
        }

        # Write config file
        try:
            _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _CONFIG_FILE.write_text(json.dumps(config_data, indent=2))
            _CONFIG_FILE.chmod(0o600)

            QMessageBox.information(self, "Settings", "Configuration saved.")
            logger.info("Config saved to %s", _CONFIG_FILE)
            self.accept()
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Failed to save config: {e}")
            logger.error("Failed to save config: %s", e)
