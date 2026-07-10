"""Settings dialog — official CodexBar config + OAuth login.

Reads/writes ``~/.config/codexbar/config.json`` (same file as
``codexbar config`` / macOS Settings → Providers).

Per provider (official fields):
- enabled
- source: auto | oauth | cli | web | api  (``usage --source``)
- cookie_source: auto | manual
- cookie_header (manual cookies)
- api_key / apiKey

OAuth actions (official login runners):
- Codex → ``codex login``
- Claude → ``claude auth login --claudeai``
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from codexbar_gui.oauth_login import (
    COOKIE_SOURCES,
    USAGE_SOURCES,
    auth_status_for,
    codex_login_status,
    find_binary,
    run_provider_login,
)

logger = logging.getLogger("codexbar_gui.config_dialog")

_CONFIG_DIR = Path.home() / ".config" / "codexbar"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_LEGACY_CONFIG = Path.home() / ".codexbar" / "config.json"

# Providers that get OAuth login buttons (official runners exist)
_OAUTH_PROVIDERS = {"codex", "claude", "gemini"}

# Short list shown by default; full list still preserved on save
_PRIMARY_PROVIDERS = (
    "codex",
    "claude",
    "openai",
    "gemini",
    "cursor",
    "copilot",
    "openrouter",
    "grok",
)


class _LoginWorker(QThread):
    finished_ok = Signal(str, object)  # provider, LoginResult

    def __init__(self, provider: str, parent=None) -> None:
        super().__init__(parent)
        self._provider = provider

    def run(self) -> None:
        result = run_provider_login(self._provider, timeout=180.0)
        self.finished_ok.emit(self._provider, result)


class ProviderConfigWidget(QWidget):
    """One provider row: enable, usage source (OAuth/…), keys, login."""

    def __init__(
        self,
        provider: dict[str, Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._id = str(provider.get("id") or "unknown")
        self._raw = dict(provider)
        self._login_worker: Optional[_LoginWorker] = None
        self._build(provider)

    def _build(self, provider: dict[str, Any]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        self._enabled = QCheckBox(self._id.replace("_", " ").title())
        self._enabled.setChecked(bool(provider.get("enabled", False)))
        self._enabled.setFont(QFont("Sans", 11, QFont.Weight.DemiBold))
        head.addWidget(self._enabled)
        head.addStretch()
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#a6adc8; font-size:11px;")
        head.addWidget(self._status, 1)
        root.addLayout(head)

        form = QFormLayout()
        form.setSpacing(6)

        # Usage source — official Preferences → Providers → Usage source
        self._source = QComboBox()
        for s in USAGE_SOURCES:
            self._source.addItem(s, s)
        cur_src = str(provider.get("source") or "auto").lower()
        idx = max(0, self._source.findData(cur_src))
        self._source.setCurrentIndex(idx)
        self._source.setToolTip(
            "auto: pick best available\n"
            "oauth: OAuth API (e.g. ~/.codex/auth.json)\n"
            "cli: provider CLI RPC\n"
            "web: browser/dashboard scrape\n"
            "api: API key"
        )
        form.addRow("Usage source", self._source)

        self._cookie_source = QComboBox()
        for s in COOKIE_SOURCES:
            self._cookie_source.addItem(s, s)
        cs = str(
            provider.get("cookie_source")
            or provider.get("cookieSource")
            or "auto"
        ).lower()
        self._cookie_source.setCurrentIndex(max(0, self._cookie_source.findData(cs)))
        form.addRow("Cookie source", self._cookie_source)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("API key (optional for OAuth providers)")
        key = provider.get("api_key") or provider.get("apiKey") or ""
        if key:
            self._api_key.setText(str(key))
            self._api_key.setPlaceholderText("•••• saved (leave blank to keep)")
        form.addRow("API key", self._api_key)

        self._cookie_header = QLineEdit()
        self._cookie_header.setPlaceholderText("Cookie: header when cookie source = manual")
        ch = provider.get("cookie_header") or provider.get("cookieHeader") or ""
        if ch:
            self._cookie_header.setText(str(ch))
        form.addRow("Cookie header", self._cookie_header)

        root.addLayout(form)

        actions = QHBoxLayout()
        if self._id in _OAUTH_PROVIDERS:
            self._login_btn = QPushButton("Login (OAuth)…")
            self._login_btn.setToolTip(
                "Codex: runs `codex login`\n"
                "Claude: runs `claude auth login --claudeai`\n"
                "Same as official CodexBar login runners."
            )
            self._login_btn.clicked.connect(self._start_login)
            actions.addWidget(self._login_btn)
        else:
            self._login_btn = None

        refresh_status = QPushButton("Refresh status")
        refresh_status.clicked.connect(self.refresh_auth_status)
        actions.addWidget(refresh_status)
        actions.addStretch()
        root.addLayout(actions)

        # visual card
        self.setStyleSheet(
            "ProviderConfigWidget { background:#1e1e2e; border:1px solid #313244; "
            "border-radius:10px; }"
        )
        self.refresh_auth_status()

    def refresh_auth_status(self) -> None:
        st = auth_status_for(self._id)
        extra = ""
        if self._id == "codex":
            # quick login status if binary present
            if find_binary("codex"):
                extra = ""
        color = {
            "oauth": "#a6e3a1",
            "api_key": "#89b4fa",
            "cookies": "#f9e2af",
            "none": "#f38ba8",
            "unknown": "#a6adc8",
        }.get(st.method, "#a6adc8")
        self._status.setText(st.label)
        self._status.setStyleSheet(f"color:{color}; font-size:11px;")

    def _start_login(self) -> None:
        if self._login_worker is not None and self._login_worker.isRunning():
            return
        if self._login_btn:
            self._login_btn.setEnabled(False)
            self._login_btn.setText("Logging in…")
        self._status.setText("OAuth login running (browser may open)…")
        self._login_worker = _LoginWorker(self._id, parent=self)
        self._login_worker.finished_ok.connect(self._on_login_done)
        self._login_worker.start()

    def _on_login_done(self, provider: str, result: object) -> None:
        if self._login_btn:
            self._login_btn.setEnabled(True)
            self._login_btn.setText("Login (OAuth)…")
        ok = getattr(result, "ok", False)
        outcome = getattr(result, "outcome", "failed")
        detail = getattr(result, "detail", "") or ""
        link = getattr(result, "auth_link", None)
        if link:
            QDesktopServices.openUrl(QUrl(link))
        if ok:
            # Prefer OAuth source after successful login
            idx = self._source.findData("oauth")
            if idx >= 0:
                self._source.setCurrentIndex(idx)
            QMessageBox.information(
                self,
                "OAuth login",
                f"{provider}: login OK ({outcome})\n\n{detail[:500]}",
            )
        else:
            QMessageBox.warning(
                self,
                "OAuth login",
                f"{provider}: {outcome}\n\n{detail[:700]}\n\n"
                "Tip: run in a terminal if browser flow needs a TTY:\n"
                "  codex login\n"
                "  claude auth login --claudeai",
            )
        self.refresh_auth_status()

    def get_state(self) -> dict[str, Any]:
        """Merge UI into official provider dict (preserve unknown keys)."""
        out = dict(self._raw)
        out["id"] = self._id
        out["enabled"] = self._enabled.isChecked()
        out["source"] = self._source.currentData() or "auto"
        out["cookie_source"] = self._cookie_source.currentData() or "auto"
        # Keep both snake_case (on-disk) and don't force-null other fields
        new_key = self._api_key.text().strip()
        if new_key:
            out["api_key"] = new_key
            out["apiKey"] = new_key
        elif "api_key" not in out and "apiKey" not in out:
            out["api_key"] = None
        # If placeholder-only empty, leave existing key in _raw
        ch = self._cookie_header.text().strip()
        out["cookie_header"] = ch or None
        return out


class ConfigDialog(QDialog):
    """Official config.json editor + OAuth login."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._config: Dict[str, Any] = {}
        self._widgets: List[ProviderConfigWidget] = []
        self._init_ui()
        self._load_config()

    def _config_path(self) -> Path:
        if _CONFIG_FILE.is_file():
            return _CONFIG_FILE
        if _LEGACY_CONFIG.is_file():
            return _LEGACY_CONFIG
        return _CONFIG_FILE

    def _init_ui(self) -> None:
        self.setWindowTitle("CodexBar Settings")
        self.setMinimumSize(720, 560)
        self.resize(760, 640)

        layout = QVBoxLayout(self)
        title = QLabel("Providers · OAuth & usage source")
        title.setFont(QFont("Sans", 13, QFont.Weight.Bold))
        layout.addWidget(title)

        hint = QLabel(
            "Config file is the same as official CodexBar / "
            f"<code>{self._config_path()}</code>. "
            "OAuth uses provider CLIs (codex login, claude auth login) — "
            "not the aipc Python port."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#a6adc8; font-size:11px;")
        layout.addWidget(hint)

        meta = QLabel(
            f"Serve (optional): http://{self._host}:{self._port} · "
            f"codex={find_binary('codex') or 'missing'} · "
            f"claude={find_binary('claude') or 'missing'}"
        )
        meta.setStyleSheet("color:#6c7086; font-size:10px;")
        layout.addWidget(meta)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_host)
        layout.addWidget(scroll, 1)

        # Global GUI refresh (local to gui.yaml-ish; store in config top-level if present)
        row = QHBoxLayout()
        row.addWidget(QLabel("GUI refresh interval:"))
        self._interval = QSpinBox()
        self._interval.setRange(10, 3600)
        self._interval.setValue(60)
        self._interval.setSuffix(" s")
        row.addWidget(self._interval)
        row.addStretch()
        reload_btn = QPushButton("Reload from disk")
        reload_btn.clicked.connect(self._load_config)
        row.addWidget(reload_btn)
        layout.addLayout(row)

        btns = QHBoxLayout()
        btns.addStretch()
        # Prefer official CLI enable when available
        cli_btn = QPushButton("Open config dir")
        cli_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(_CONFIG_DIR)))
        )
        btns.addWidget(cli_btn)
        save = QPushButton("Save")
        save.clicked.connect(self._save_config)
        btns.addWidget(save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def _clear_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._widgets.clear()

    def _load_config(self) -> None:
        self._clear_list()
        path = self._config_path()
        data: Dict[str, Any] = {"version": 1, "providers": []}
        if path.is_file():
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("config load: %s", exc)
        self._config = data

        # Optional: merge enablement from `codexbar config providers` when dump available
        providers = list(data.get("providers") or [])
        by_id = {str(p.get("id")): p for p in providers if isinstance(p, dict)}

        # Ensure primary providers exist
        for pid in _PRIMARY_PROVIDERS:
            if pid not in by_id:
                by_id[pid] = {
                    "id": pid,
                    "enabled": pid in {"codex", "claude"},
                    "source": "auto",
                    "cookie_source": "auto",
                    "api_key": None,
                    "cookie_header": None,
                }

        # Show primary first, then any other enabled from file
        ordered: List[dict] = []
        seen = set()
        for pid in _PRIMARY_PROVIDERS:
            ordered.append(by_id[pid])
            seen.add(pid)
        for pid, prov in by_id.items():
            if pid not in seen and prov.get("enabled"):
                ordered.append(prov)
                seen.add(pid)

        self._list_layout.addStretch()
        # insert before stretch
        stretch = self._list_layout.takeAt(self._list_layout.count() - 1)
        for prov in ordered:
            w = ProviderConfigWidget(prov)
            self._widgets.append(w)
            self._list_layout.addWidget(w)
        self._list_layout.addItem(stretch)

        # interval from gui extras if any
        gui = data.get("gui") if isinstance(data.get("gui"), dict) else {}
        self._interval.setValue(int(gui.get("refresh_interval") or data.get("refresh_interval") or 60))

    def _save_config(self) -> None:
        path = self._config_path()
        # Start from full on-disk list so we don't drop 50+ providers
        existing = list(self._config.get("providers") or [])
        by_id: Dict[str, dict] = {
            str(p.get("id")): dict(p) for p in existing if isinstance(p, dict)
        }

        for w in self._widgets:
            st = w.get_state()
            pid = st["id"]
            base = by_id.get(pid, {"id": pid})
            base.update(st)
            # Prefer snake_case on disk (matches user's current file)
            if "apiKey" in base and "api_key" not in base:
                base["api_key"] = base.get("apiKey")
            # Don't write empty string over existing key if user left field blank
            if not (st.get("api_key") or st.get("apiKey")):
                # restore previous key if any
                prev = by_id.get(pid, {})
                if prev.get("api_key") or prev.get("apiKey"):
                    base["api_key"] = prev.get("api_key") or prev.get("apiKey")
                else:
                    base["api_key"] = None
            by_id[pid] = base

            # Mirror enable via official CLI when available
            self._cli_set_enabled(pid, bool(st.get("enabled")))

        providers_out = list(by_id.values())
        # stable-ish order: primary first
        providers_out.sort(
            key=lambda p: (
                _PRIMARY_PROVIDERS.index(p["id"])
                if p.get("id") in _PRIMARY_PROVIDERS
                else 1000,
                str(p.get("id")),
            )
        )

        out = dict(self._config)
        out["version"] = out.get("version", 1)
        out["providers"] = providers_out
        out["gui"] = {
            **(out.get("gui") if isinstance(out.get("gui"), dict) else {}),
            "refresh_interval": self._interval.value(),
        }

        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
            path.chmod(0o600)
            # Validate with official CLI when present
            self._cli_validate()
            QMessageBox.information(
                self,
                "Settings",
                f"Saved to {path}\n\n"
                "OAuth sessions stay in provider homes "
                "(~/.codex/auth.json, Claude credentials).",
            )
            logger.info("config saved %s", path)
            self.accept()
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"Failed to save: {exc}")

    def _cli_set_enabled(self, provider: str, enabled: bool) -> None:
        binary = shutil.which("codexbar") or find_binary("codexbar")
        if not binary:
            return
        cmd = [
            binary,
            "config",
            "enable" if enabled else "disable",
            "--provider",
            provider,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        except Exception as exc:
            logger.debug("cli enable/disable %s: %s", provider, exc)

    def _cli_validate(self) -> None:
        binary = shutil.which("codexbar") or find_binary("codexbar")
        if not binary:
            return
        try:
            subprocess.run(
                [binary, "config", "validate"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except Exception:
            pass
