"""Settings dialog — official CodexBar config + OAuth login.

Reads/writes ``~/.config/codexbar/config.json`` (same file as
``codexbar config`` / macOS Settings → Providers).

Layout follows official CodexBar Settings: a category sidebar (General /
Providers / Advanced) on the left, detail pane on the right. The Providers
category itself splits again — a scannable provider list on the left, the
selected provider's full form (incl. token accounts) on the right — instead
of one long scroll of every provider stacked on top of each other.

Per provider (official fields):
- enabled
- source: auto | oauth | cli | web | api  (``usage --source``)
- cookie_source: auto | manual
- cookie_header (manual cookies)
- api_key / apiKey
- tokenAccounts: {version, activeIndex, accounts:[{id,label,token,addedAt,lastUsed}]}
  (camelCase only — the CLI silently ignores a snake_case ``token_accounts``)

OAuth actions (official login runners):
- Codex → ``codex login``
- Claude → ``claude auth login --claudeai``
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from codexbar_gui.claude_oauth import is_ccs_owned
from codexbar_gui.i18n import current_language, set_language, t
from codexbar_gui.menu_bar import (
    ICON_STYLE,
    PROVIDER_SELECTION,
    SHOW_AS,
    MenuBarSettings,
    load_menu_bar_settings,
    merge_menu_bar_into_gui,
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

# Providers that get real OAuth CLI runners (browser login).
# Grok / zai / most others are API key or browser-cookie (web) — not OAuth.
_OAUTH_PROVIDERS = {"codex", "claude", "gemini"}

# Friendly labels (official id may differ from product name)
_DISPLAY_NAMES = {
    "codex": "Codex",
    "claude": "Claude",
    "openai": "OpenAI Admin",
    "gemini": "Gemini",
    "cursor": "Cursor",
    "copilot": "GitHub Copilot",
    "openrouter": "OpenRouter",
    "grok": "Grok (xAI)",
    "zai": "Z.ai / GLM (BigModel)",
    "minimax": "MiniMax",
    "kimi": "Kimi",
    "kimik2": "Kimi K2",
    "deepseek": "DeepSeek",
    "litellm": "LiteLLM",
    "mistral": "Mistral",
    "perplexity": "Perplexity",
    "windsurf": "Windsurf",
    "zed": "Zed",
    "moonshot": "Moonshot",
    "doubao": "Doubao",
    "qoder": "Qoder",
    "stepfun": "StepFun",
}

# How each provider actually authenticates (shown in UI so OAuth isn't expected)
_AUTH_HINTS = {
    "codex": "OAuth via `codex login` → ~/.codex/auth.json",
    "claude": "OAuth via `claude auth login` or API key",
    "gemini": "OAuth via `gemini auth login` or API key",
    "openai": "Admin API key only (no ChatGPT OAuth here)",
    "grok": "No OAuth. SuperGrok quota uses web cookies (source=web) or XAI_API_KEY (source=api)",
    "zai": "Zhipu / z.ai coding plan — API key (Z_AI_API_KEY). No browser OAuth in CodexBar",
    "openrouter": "API key (OPENROUTER_API_KEY)",
    "deepseek": "API key",
    "minimax": "API key",
    "kimi": "API key / cookies (provider-specific)",
    "copilot": "gh auth / device flow",
    "cursor": "Browser cookies or API key",
    "litellm": "Proxy URL + master key",
}

# Featured list in Settings (full catalog = 50+; toggle "Show all")
_PRIMARY_PROVIDERS = (
    "codex",
    "claude",
    "openai",
    "gemini",
    "grok",
    "zai",  # GLM / BigModel coding plan
    "cursor",
    "copilot",
    "openrouter",
    "deepseek",
    "minimax",
    "kimi",
    "litellm",
    "mistral",
    "perplexity",
    "windsurf",
    "zed",
)


def _display_name(pid: str) -> str:
    return _DISPLAY_NAMES.get(pid, pid.replace("_", " ").replace("-", " ").title())


class _LoginWorker(QThread):
    finished_ok = Signal(str, object)  # provider, LoginResult

    def __init__(self, provider: str, parent=None) -> None:
        super().__init__(parent)
        self._provider = provider

    def run(self) -> None:
        result = run_provider_login(self._provider, timeout=180.0)
        self.finished_ok.emit(self._provider, result)


class _TokenAccountDialog(QDialog):
    """Add / edit one ``tokenAccounts.accounts[]`` row. Token field is masked
    and never echoed anywhere else (message boxes, logs)."""

    def __init__(
        self,
        provider_id: str,
        label: str = "",
        token: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("token_account_edit") if label else t("token_account_add"))
        form = QFormLayout(self)
        form.setSpacing(8)

        self._label = QLineEdit(label)
        self._label.setPlaceholderText(t("token_account_label_ph"))
        form.addRow(t("token_account_label"), self._label)

        self._token = QLineEdit(token)
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        ph = (
            "sk-ant-oat... or sessionKey cookie"
            if provider_id == "claude"
            else t("token_account_token_ph")
        )
        self._token.setPlaceholderText(ph)
        form.addRow(t("token_account_token"), self._token)

        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton(t("save"))
        ok.setDefault(True)
        ok.clicked.connect(self._on_accept)
        btns.addWidget(ok)
        cancel = QPushButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        form.addRow(btns)

    def _on_accept(self) -> None:
        if not self._label.text().strip() or not self._token.text().strip():
            QMessageBox.warning(self, t("error"), t("token_account_required"))
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self._label.text().strip(), self._token.text()


class TokenAccountsEditor(QWidget):
    """Add / edit / remove ``tokenAccounts`` rows for one provider.

    ccs-managed Claude rows (``id == uuid5(ACCOUNT_NS, label)``, see
    ``claude_oauth.sync_token_accounts``) show a "ccs" badge and cannot be
    edited here — the next poll overwrites the token anyway.
    """

    def __init__(
        self,
        provider_id: str,
        token_accounts: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._provider_id = provider_id
        data = token_accounts if isinstance(token_accounts, dict) else {}
        self._accounts: List[dict] = [
            dict(a) for a in (data.get("accounts") or []) if isinstance(a, dict)
        ]
        try:
            self._active = int(data.get("activeIndex") or 0)
        except (TypeError, ValueError):
            self._active = 0
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        hint = QLabel(t("token_accounts_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6c7086; font-size:10px;")
        root.addWidget(hint)

        self._listw = QListWidget()
        self._listw.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._listw.setMaximumHeight(96)
        self._listw.itemSelectionChanged.connect(self._sync_buttons)
        root.addWidget(self._listw)

        row = QHBoxLayout()
        self._add_btn = QPushButton(t("token_account_add_btn"))
        self._add_btn.clicked.connect(self._add)
        row.addWidget(self._add_btn)
        self._edit_btn = QPushButton(t("token_account_edit_btn"))
        self._edit_btn.clicked.connect(self._edit)
        row.addWidget(self._edit_btn)
        self._remove_btn = QPushButton(t("token_account_remove_btn"))
        self._remove_btn.clicked.connect(self._remove)
        row.addWidget(self._remove_btn)
        self._active_btn = QPushButton(t("token_account_set_active_btn"))
        self._active_btn.clicked.connect(self._set_active)
        row.addWidget(self._active_btn)
        row.addStretch()
        root.addLayout(row)

        self._populate()

    def _is_ccs(self, account: dict) -> bool:
        return self._provider_id == "claude" and is_ccs_owned(account)

    def _populate(self) -> None:
        self._listw.clear()
        if not self._accounts:
            placeholder = QListWidgetItem(t("no_token_accounts"))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._listw.addItem(placeholder)
            self._sync_buttons()
            return
        for i, a in enumerate(self._accounts):
            label = str(a.get("label") or "(no label)")
            tok = str(a.get("token") or "")
            masked = ("••••" + tok[-4:]) if tok else "—"
            marker = " ★" if i == self._active else ""
            badge = f"  [{t('token_account_ccs_badge')}]" if self._is_ccs(a) else ""
            item = QListWidgetItem(f"{label}{marker}   ·   {masked}{badge}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._listw.addItem(item)
        self._listw.setCurrentRow(min(self._active, len(self._accounts) - 1))
        self._sync_buttons()

    def _current_index(self) -> int:
        item = self._listw.currentItem()
        if item is None:
            return -1
        idx = item.data(Qt.ItemDataRole.UserRole)
        return int(idx) if idx is not None else -1

    def _sync_buttons(self) -> None:
        idx = self._current_index()
        has_sel = idx >= 0
        locked = has_sel and self._is_ccs(self._accounts[idx])
        self._edit_btn.setEnabled(has_sel and not locked)
        self._edit_btn.setToolTip(t("token_account_ccs_locked") if locked else "")
        # Remove looks like it works but doesn't durably: the next 60s ccs
        # poll re-adds the row. Disable it too, same as Edit.
        self._remove_btn.setEnabled(has_sel and not locked)
        self._remove_btn.setToolTip(t("token_account_ccs_locked_remove") if locked else "")
        self._active_btn.setEnabled(has_sel and idx != self._active)

    def _add(self) -> None:
        dlg = _TokenAccountDialog(self._provider_id, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        label, token = dlg.values()
        now = int(time.time())
        self._accounts.append(
            {
                "id": str(uuid.uuid4()),
                "label": label,
                "token": token,
                "addedAt": now,
                "lastUsed": now,
            }
        )
        if len(self._accounts) == 1:
            self._active = 0
        self._populate()

    def _edit(self) -> None:
        idx = self._current_index()
        if idx < 0 or self._is_ccs(self._accounts[idx]):
            return
        acc = self._accounts[idx]
        dlg = _TokenAccountDialog(
            self._provider_id,
            str(acc.get("label") or ""),
            str(acc.get("token") or ""),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        label, token = dlg.values()
        acc["label"] = label
        acc["token"] = token
        self._populate()

    def _remove(self) -> None:
        idx = self._current_index()
        if idx < 0 or self._is_ccs(self._accounts[idx]):
            return
        label = str(self._accounts[idx].get("label") or "")
        if (
            QMessageBox.question(
                self,
                t("token_account_remove_btn"),
                t("remove_account_confirm", label=label),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        del self._accounts[idx]
        if self._active >= len(self._accounts):
            self._active = max(0, len(self._accounts) - 1)
        elif self._active > idx:
            self._active -= 1
        self._populate()

    def _set_active(self) -> None:
        idx = self._current_index()
        if idx < 0:
            return
        self._active = idx
        self._populate()

    def get_state(self) -> Optional[dict]:
        """camelCase ``tokenAccounts`` block, or ``None`` when the list is empty."""
        if not self._accounts:
            return None
        return {
            "version": 1,
            "activeIndex": max(0, min(self._active, len(self._accounts) - 1)),
            "accounts": [dict(a) for a in self._accounts],
        }


def _reconcile_token_accounts(
    disk_ta: Any, widget_ta: Any, provider_id: str
) -> Optional[dict]:
    """Merge a widget's ``tokenAccounts`` onto what's actually on disk right now.

    ccs-owned rows are locked in the editor (Edit/Remove disabled) — they are
    never user-edited, so the widget's in-memory copy of one can only be
    stale (the tray resyncs every ~60s while Settings may sit open for
    minutes). The fresh on-disk value always wins for those, including a ccs
    account added or dropped by a sync that happened after this dialog
    opened. Everything else — a hand-added or hand-edited account — follows
    the widget, since that's the user's own edit and disk has no opinion on it.
    """
    widget_accounts = [a for a in (widget_ta or {}).get("accounts") or [] if isinstance(a, dict)]
    disk_accounts = [a for a in (disk_ta or {}).get("accounts") or [] if isinstance(a, dict)]
    disk_by_account_id = {str(a.get("id")): a for a in disk_accounts}

    merged: List[dict] = []
    seen: set[str] = set()
    for acc in widget_accounts:
        aid = str(acc.get("id"))
        if provider_id == "claude" and is_ccs_owned(acc):
            fresh = disk_by_account_id.get(aid)
            if fresh is not None:
                merged.append(fresh)
                seen.add(aid)
            # else: the sync dropped it (profile logged out) since this
            # dialog opened — respect that instead of resurrecting it.
        else:
            merged.append(acc)
            seen.add(aid)
    for acc in disk_accounts:
        aid = str(acc.get("id"))
        if aid not in seen and provider_id == "claude" and is_ccs_owned(acc):
            # A ccs account the sync added after this dialog opened —
            # keep it instead of silently dropping it on save.
            merged.append(acc)
            seen.add(aid)

    if not merged:
        return None
    active = (widget_ta or {}).get("activeIndex") if isinstance(widget_ta, dict) else 0
    active = active if isinstance(active, int) and 0 <= active < len(merged) else 0
    return {"version": 1, "activeIndex": active, "accounts": merged}


class ProviderConfigWidget(QWidget):
    """One provider's full config: enable, usage source, keys, login, accounts."""

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
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        head = QHBoxLayout()
        self._enabled = QCheckBox(_display_name(self._id))
        self._enabled.setChecked(bool(provider.get("enabled", False)))
        self._enabled.setFont(QFont("Sans", 12, QFont.Weight.DemiBold))
        self._enabled.setToolTip(f"Official id: {self._id}")
        head.addWidget(self._enabled)
        id_lab = QLabel(f"`{self._id}`")
        id_lab.setStyleSheet("color:#6c7086; font-size:10px;")
        head.addWidget(id_lab)
        head.addStretch()
        root.addLayout(head)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#a6adc8; font-size:11px;")
        root.addWidget(self._status)

        hint = _AUTH_HINTS.get(self._id)
        if hint:
            hl = QLabel(hint)
            hl.setWordWrap(True)
            hl.setStyleSheet("color:#6c7086; font-size:10px;")
            root.addWidget(hl)

        form = QFormLayout()
        form.setSpacing(8)
        form.setHorizontalSpacing(16)

        # Usage source — official Preferences → Providers → Usage source
        self._source = QComboBox()
        for s in USAGE_SOURCES:
            self._source.addItem(s, s)
        cur_src = str(provider.get("source") or "auto").lower()
        # Grok SuperGrok quota is web-cookies; prefer web if still on bare auto+disabled
        if self._id == "grok" and cur_src == "auto" and not provider.get("enabled"):
            cur_src = "web"
        idx = max(0, self._source.findData(cur_src))
        self._source.setCurrentIndex(idx)
        self._source.setToolTip(
            "auto: pick best available\n"
            "oauth: OAuth API (Codex/Claude only)\n"
            "cli: provider CLI RPC\n"
            "web: browser/dashboard cookies (Grok SuperGrok)\n"
            "api: API key"
        )
        form.addRow(t("usage_source"), self._source)

        self._cookie_source = QComboBox()
        for s in COOKIE_SOURCES:
            self._cookie_source.addItem(s, s)
        cs = str(
            provider.get("cookie_source")
            or provider.get("cookieSource")
            or "auto"
        ).lower()
        self._cookie_source.setCurrentIndex(max(0, self._cookie_source.findData(cs)))
        form.addRow(t("cookie_source"), self._cookie_source)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        ph = {
            "grok": "xAI API key (XAI_API_KEY) — optional if SuperGrok web works",
            "zai": "Z_AI_API_KEY / BigModel key",
            "openrouter": "OPENROUTER_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }.get(self._id, "API key (when source=api)")
        self._api_key.setPlaceholderText(ph)
        key = provider.get("api_key") or provider.get("apiKey") or ""
        if key:
            self._api_key.setText(str(key))
            self._api_key.setPlaceholderText("•••• saved (leave blank to keep)")
        form.addRow(t("api_key"), self._api_key)

        self._cookie_header = QLineEdit()
        self._cookie_header.setPlaceholderText("Cookie: header when cookie source = manual")
        ch = provider.get("cookie_header") or provider.get("cookieHeader") or ""
        if ch:
            self._cookie_header.setText(str(ch))
        form.addRow(t("cookie_header"), self._cookie_header)

        root.addLayout(form)

        actions = QHBoxLayout()
        if self._id in _OAUTH_PROVIDERS:
            self._login_btn = QPushButton(t("login_oauth"))
            self._login_btn.setToolTip(
                "Codex: runs `codex login`\n"
                "Claude: runs `claude auth login --claudeai`\n"
                "Same as official CodexBar login runners."
            )
            self._login_btn.clicked.connect(self._start_login)
            actions.addWidget(self._login_btn)
        elif self._id == "grok":
            help_btn = QPushButton("Grok connect help…")
            help_btn.clicked.connect(self._grok_help)
            actions.addWidget(help_btn)
            web_btn = QPushButton("Open x.ai")
            web_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl("https://console.x.ai/"))
            )
            actions.addWidget(web_btn)
            self._login_btn = None
        elif self._id == "zai":
            help_btn = QPushButton("GLM / Z.ai help…")
            help_btn.clicked.connect(self._zai_help)
            actions.addWidget(help_btn)
            self._login_btn = None
        else:
            self._login_btn = None

        refresh_status = QPushButton(t("refresh_status"))
        refresh_status.clicked.connect(self.refresh_auth_status)
        actions.addWidget(refresh_status)
        actions.addStretch()
        root.addLayout(actions)

        ta_group = QGroupBox(t("token_accounts_heading"))
        ta_layout = QVBoxLayout(ta_group)
        ta_layout.setContentsMargins(10, 6, 10, 8)
        ta_layout.setSpacing(4)
        self._accounts_editor = TokenAccountsEditor(
            self._id, provider.get("tokenAccounts"), parent=ta_group
        )
        ta_layout.addWidget(self._accounts_editor)
        root.addWidget(ta_group)

        root.addStretch()
        self.refresh_auth_status()

    def _grok_help(self) -> None:
        QMessageBox.information(
            self,
            "Grok (xAI) — no OAuth login",
            "CodexBar does <b>not</b> support browser OAuth for Grok "
            "(unlike Codex / Claude).<br><br>"
            "<b>Option A — SuperGrok quota (recommended)</b><br>"
            "1. Log into x.ai / grok.com in a normal browser<br>"
            "2. Set Usage source = <code>web</code> (or auto)<br>"
            "3. Enable Grok and Save — CLI uses <code>grok-web</code> cookies<br><br>"
            "<b>Option B — API spend</b><br>"
            "Paste <code>XAI_API_KEY</code> below, source = <code>api</code>.<br><br>"
            "CLI check: <code>codexbar usage --provider grok --pretty</code>",
        )

    def _zai_help(self) -> None:
        QMessageBox.information(
            self,
            "Z.ai / GLM (BigModel)",
            "In official CodexBar the provider id is <b>zai</b> "
            "(z.ai coding plan / Zhipu BigModel) — there is no separate "
            "<code>glm</code> id.<br><br>"
            "Auth is <b>API key only</b> (no OAuth button):<br>"
            "<code>printf '%s' \"$Z_AI_API_KEY\" | codexbar config set-api-key "
            "--provider zai --stdin</code><br><br>"
            "Team usage may need org/project ids "
            "(see <code>codexbar config set-api-key --help</code>).",
        )

    def refresh_auth_status(self) -> None:
        st = auth_status_for(self._id)
        color = {
            "oauth": "#a6e3a1",
            "api_key": "#89b4fa",
            "cookies": "#f9e2af",
            "web": "#f9e2af",
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
            self._login_btn.setText(t("logging_in"))
        self._status.setText(t("oauth_running"))
        self._login_worker = _LoginWorker(self._id, parent=self)
        self._login_worker.finished_ok.connect(self._on_login_done)
        self._login_worker.start()

    def _on_login_done(self, provider: str, result: object) -> None:
        if self._login_btn:
            self._login_btn.setEnabled(True)
            self._login_btn.setText(t("login_oauth"))
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

        # camelCase only — the CLI ignores a snake_case token_accounts block.
        ta = self._accounts_editor.get_state()
        if ta is not None:
            out["tokenAccounts"] = ta
        elif "tokenAccounts" in out:
            del out["tokenAccounts"]
        return out


class ConfigDialog(QDialog):
    """Official config.json editor + OAuth login.

    Category sidebar (General / Providers / Advanced) on the left; detail
    pane on the right. Providers has its own list+detail split so only one
    provider's form is on screen at a time.
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

    # ── UI scaffold ─────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        self.setWindowTitle(t("settings_title"))
        self.setMinimumSize(940, 700)
        # Tall enough that a provider's full form (incl. token accounts and
        # its button row) fits without scrolling at default size — the
        # original 980x680 clipped the token-accounts buttons (#1 follow-up).
        self.resize(1060, 860)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        title = QLabel(t("settings_heading"))
        title.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        outer.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        self._categories = QListWidget()
        self._categories.setFixedWidth(170)
        self._categories.setSpacing(2)
        for key in ("category_general", "category_providers", "category_advanced"):
            self._categories.addItem(t(key))
        self._categories.currentRowChanged.connect(self._on_category_changed)
        body.addWidget(self._categories)

        self._pages = QStackedWidget()
        body.addWidget(self._pages, 1)
        self._pages.addWidget(self._build_general_page())
        self._pages.addWidget(self._build_providers_page())
        self._pages.addWidget(self._build_advanced_page())
        self._categories.setCurrentRow(0)

        btns = QHBoxLayout()
        btns.addStretch()
        save = QPushButton(t("save"))
        save.clicked.connect(self._save_config)
        btns.addWidget(save)
        cancel = QPushButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        outer.addLayout(btns)

    def _on_category_changed(self, row: int) -> None:
        self._pages.setCurrentIndex(max(0, row))

    def _build_general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        head = QLabel(t("menu_bar_display"))
        head.setFont(QFont("Sans", 12, QFont.Weight.DemiBold))
        layout.addWidget(head)
        note = QLabel(t("menu_bar_note"))
        note.setWordWrap(True)
        note.setStyleSheet("color:#a6adc8; font-size:11px;")
        layout.addWidget(note)

        form = QFormLayout()
        form.setSpacing(14)
        form.setHorizontalSpacing(20)

        self._lang = QComboBox()
        self._lang.addItem(t("lang_auto"), "auto")
        self._lang.addItem(t("lang_en"), "en")
        self._lang.addItem(t("lang_zh_tw"), "zh_TW")
        self._lang.addItem(t("lang_zh_cn"), "zh_CN")
        form.addRow(t("language"), self._lang)

        self._sel = QComboBox()
        self._sel.addItem(t("sel_highest"), "highest_usage")
        self._sel.addItem(t("sel_first"), "first_enabled")
        self._sel.addItem(t("sel_pinned"), "pinned")
        self._sel.setToolTip(
            "Official “highest-usage auto-selection” vs fixed provider for the tray icon."
        )
        form.addRow(t("tray_provider"), self._sel)

        self._pin = QComboBox()
        for pid in (
            "codex",
            "claude",
            "zai",
            "grok",
            "gemini",
            "cursor",
            "copilot",
            "openrouter",
            "deepseek",
        ):
            self._pin.addItem(pid, pid)
        self._pin.setEditable(True)
        form.addRow(t("pinned_id"), self._pin)

        self._show_as = QComboBox()
        self._show_as.addItem(t("show_remaining"), "remaining")
        self._show_as.addItem(t("show_used"), "used")
        self._show_as.setToolTip(
            "Official: fill = remaining by default; “Show usage as used” flips the bar."
        )
        form.addRow(t("bar_fill"), self._show_as)

        self._icon_style = QComboBox()
        self._icon_style.addItem(t("icon_dual"), "dual_bars")
        self._icon_style.addItem(t("icon_primary"), "primary_only")
        self._icon_style.addItem(t("icon_brand"), "brand_percent")
        form.addRow(t("icon_style"), self._icon_style)

        self._overview = QLineEdit()
        self._overview.setPlaceholderText(t("overview_placeholder"))
        self._overview.setToolTip(
            "Official “Overview tab providers” — comma-separated ids; listed first in Overview."
        )
        form.addRow(t("overview_providers"), self._overview)

        self._tip_pct = QCheckBox(t("show_percent_tooltip"))
        self._tip_pct.setChecked(True)
        form.addRow("", self._tip_pct)

        self._interval = QSpinBox()
        self._interval.setRange(10, 3600)
        self._interval.setValue(60)
        self._interval.setSuffix(t("seconds_suffix"))
        self._interval.setToolTip("Refresh cadence (official presets: 1m / 2m / 5m / 15m)")
        form.addRow(t("refresh_interval"), self._interval)

        layout.addLayout(form)
        layout.addStretch()
        return page

    def _build_providers_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        head_row = QHBoxLayout()
        head = QLabel(t("providers"))
        head.setFont(QFont("Sans", 12, QFont.Weight.DemiBold))
        head_row.addWidget(head)
        head_row.addStretch()
        layout.addLayout(head_row)

        self._show_all = QCheckBox(t("show_all_providers"))
        self._show_all.setToolTip(
            "When off: featured list (Codex, Claude, Grok, Z.ai/GLM, …). "
            "When on: every id from config.json (~50+)."
        )
        self._show_all.toggled.connect(lambda _=False: self._load_config())
        layout.addWidget(self._show_all)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(4)
        self._provider_list = QListWidget()
        self._provider_list.currentRowChanged.connect(self._on_provider_selected)
        left_l.addWidget(self._provider_list, 1)
        self._provider_note = QLabel("")
        self._provider_note.setWordWrap(True)
        self._provider_note.setStyleSheet("color:#6c7086; font-size:10px;")
        left_l.addWidget(self._provider_note)
        split.addWidget(left)

        self._provider_stack = QStackedWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._provider_stack)
        split.addWidget(scroll)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 640])

        layout.addWidget(split, 1)
        return page

    def _build_advanced_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        head = QLabel(t("settings_about"))
        head.setFont(QFont("Sans", 12, QFont.Weight.DemiBold))
        layout.addWidget(head)

        self._hint = QLabel(t("settings_hint", path=f"<code>{self._config_path()}</code>"))
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#a6adc8; font-size:11px;")
        layout.addWidget(self._hint)

        self._meta = QLabel(
            f"Serve (optional): http://{self._host}:{self._port} · "
            f"codex={find_binary('codex') or 'missing'} · "
            f"claude={find_binary('claude') or 'missing'}"
        )
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color:#6c7086; font-size:10px;")
        layout.addWidget(self._meta)

        row = QHBoxLayout()
        reload_btn = QPushButton(t("reload_disk"))
        reload_btn.clicked.connect(self._load_config)
        row.addWidget(reload_btn)
        cli_btn = QPushButton(t("open_config_dir"))
        cli_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(_CONFIG_DIR)))
        )
        row.addWidget(cli_btn)
        row.addStretch()
        layout.addLayout(row)

        layout.addStretch()
        return page

    # ── provider list/detail wiring ─────────────────────────────────────

    def _on_provider_selected(self, row: int) -> None:
        self._provider_stack.setCurrentIndex(max(0, row))

    def _provider_row_text(self, prov: dict) -> str:
        name = _display_name(str(prov.get("id") or ""))
        marker = "●" if prov.get("enabled") else "○"
        src = str(prov.get("source") or "auto")
        n = 0
        ta = prov.get("tokenAccounts")
        if isinstance(ta, dict):
            n = len(ta.get("accounts") or [])
        suffix = f"  ({n} accounts)" if n >= 2 else ""
        return f"{marker}  {name}   ·   {src}{suffix}"

    def _clear_providers(self) -> None:
        self._provider_list.clear()
        while self._provider_stack.count():
            w = self._provider_stack.widget(0)
            self._provider_stack.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

    @staticmethod
    def _read_config_file(path: Path) -> Dict[str, Any]:
        data: Dict[str, Any] = {"version": 1, "providers": []}
        if path.is_file():
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("config read %s: %s", path, exc)
        return data if isinstance(data, dict) else {"version": 1, "providers": []}

    def _load_config(self) -> None:
        self._clear_providers()
        path = self._config_path()
        data = self._read_config_file(path)
        self._config = data

        # Optional: merge enablement from `codexbar config providers` when dump available
        providers = list(data.get("providers") or [])
        by_id = {str(p.get("id")): p for p in providers if isinstance(p, dict)}

        # Ensure featured providers exist in map
        for pid in _PRIMARY_PROVIDERS:
            if pid not in by_id:
                by_id[pid] = {
                    "id": pid,
                    "enabled": pid in {"codex", "claude"},
                    "source": "web" if pid == "grok" else "auto",
                    "cookie_source": "auto",
                    "api_key": None,
                    "cookie_header": None,
                }

        show_all = bool(getattr(self, "_show_all", None) and self._show_all.isChecked())
        ordered: List[dict] = []
        seen = set()
        for pid in _PRIMARY_PROVIDERS:
            if pid in by_id:
                ordered.append(by_id[pid])
                seen.add(pid)
        # Always surface already-enabled providers outside featured list
        for pid, prov in sorted(by_id.items(), key=lambda kv: kv[0]):
            if pid in seen:
                continue
            if show_all or prov.get("enabled"):
                ordered.append(prov)
                seen.add(pid)

        for prov in ordered:
            w = ProviderConfigWidget(prov)
            self._widgets.append(w)
            self._provider_stack.addWidget(w)
            self._provider_list.addItem(QListWidgetItem(self._provider_row_text(prov)))

        if self._provider_list.count():
            self._provider_list.setCurrentRow(0)
            self._provider_stack.setCurrentIndex(0)

        self._provider_note.setText(
            "" if show_all else t("showing_featured", n=len(ordered), total=len(by_id))
        )

        # Display / menu bar
        mb = load_menu_bar_settings(path if path.is_file() else None)
        idx = max(0, self._sel.findData(mb.provider_selection))
        self._sel.setCurrentIndex(idx)
        pin_idx = self._pin.findData(mb.pinned_provider)
        if pin_idx >= 0:
            self._pin.setCurrentIndex(pin_idx)
        else:
            self._pin.setEditText(mb.pinned_provider)
        sa = max(0, self._show_as.findData(mb.show_as))
        self._show_as.setCurrentIndex(sa)
        istyle = max(0, self._icon_style.findData(mb.icon_style))
        self._icon_style.setCurrentIndex(istyle)
        self._overview.setText(",".join(mb.overview_providers))
        self._tip_pct.setChecked(mb.show_percent_tooltip)
        self._interval.setValue(int(mb.refresh_interval or 60))

        gui = self._config.get("gui") if isinstance(self._config.get("gui"), dict) else {}
        lang_raw = str(gui.get("language") or "auto")
        lang_idx = self._lang.findData(lang_raw)
        if lang_idx < 0:
            # stored effective code → select that; bare empty → auto
            lang_idx = self._lang.findData(current_language())
        self._lang.setCurrentIndex(max(0, lang_idx))

    def _save_config(self) -> None:
        path = self._config_path()
        # Re-read from disk right before merging — not the dialog's open-time
        # snapshot. The tray resyncs ccs Claude tokens every ~60s (and
        # `codexbar config …` can write independently); merging onto a stale
        # snapshot would silently write a rotated token back to its old
        # value. `by_id` starts as a copy of the fresh read so we don't drop
        # the 50+ providers the widgets never touched; `disk_by_id` stays
        # pristine so token-account reconciliation below always compares
        # against what's actually on disk right now, not our own in-progress
        # edits.
        on_disk = self._read_config_file(path)
        disk_by_id: Dict[str, dict] = {
            str(p.get("id")): p for p in (on_disk.get("providers") or []) if isinstance(p, dict)
        }
        by_id: Dict[str, dict] = {pid: dict(p) for pid, p in disk_by_id.items()}

        for w in self._widgets:
            st = w.get_state()
            pid = st["id"]
            base = by_id.get(pid, {"id": pid})
            fresh_ta = (disk_by_id.get(pid) or {}).get("tokenAccounts")
            base.update(st)
            merged_ta = _reconcile_token_accounts(fresh_ta, st.get("tokenAccounts"), pid)
            if merged_ta is not None:
                base["tokenAccounts"] = merged_ta
            elif "tokenAccounts" in base:
                del base["tokenAccounts"]
            # Prefer snake_case on disk (matches user's current file)
            if "apiKey" in base and "api_key" not in base:
                base["api_key"] = base.get("apiKey")
            # Don't write empty string over existing key if user left field blank
            if not (st.get("api_key") or st.get("apiKey")):
                # restore previous key if any
                prev = disk_by_id.get(pid, {})
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

        out = dict(on_disk)
        out["version"] = out.get("version", 1)
        out["providers"] = providers_out

        ov_raw = self._overview.text().strip()
        ov_ids = [x.strip().lower() for x in ov_raw.split(",") if x.strip()]
        pin = self._pin.currentData() or self._pin.currentText().strip() or "codex"
        mb = MenuBarSettings(
            provider_selection=str(self._sel.currentData() or "highest_usage"),
            pinned_provider=str(pin).lower(),
            show_as=str(self._show_as.currentData() or "remaining"),
            icon_style=str(self._icon_style.currentData() or "dual_bars"),
            overview_providers=ov_ids,
            show_percent_tooltip=self._tip_pct.isChecked(),
            refresh_interval=int(self._interval.value()),
        )
        gui = merge_menu_bar_into_gui(
            out.get("gui") if isinstance(out.get("gui"), dict) else {},
            mb,
        )
        lang_code = str(self._lang.currentData() or "auto")
        gui["language"] = lang_code
        out["gui"] = gui

        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
            path.chmod(0o600)
            # Apply language immediately for tray/popover chrome
            set_language(None if lang_code == "auto" else lang_code)
            # Validate with official CLI when present
            self._cli_validate()
            QMessageBox.information(
                self,
                t("settings_saved"),
                f"Saved to {path}\n\n"
                f"{t('saved_settings')}\n"
                f"{t('lang_applied')}",
            )
            logger.info("config saved %s lang=%s", path, lang_code)
            self.accept()
        except OSError as exc:
            QMessageBox.critical(self, t("error"), t("failed_save", err=exc))

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
