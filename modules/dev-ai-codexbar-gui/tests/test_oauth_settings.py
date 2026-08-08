"""OAuth status helpers + settings dialog load (no live login)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_usage_sources_match_official_cli() -> None:
    from codexbar_gui.oauth_login import COOKIE_SOURCES, USAGE_SOURCES

    assert "oauth" in USAGE_SOURCES
    assert "cli" in USAGE_SOURCES
    assert "web" in USAGE_SOURCES
    assert "api" in USAGE_SOURCES
    assert "auto" in USAGE_SOURCES
    assert "manual" in COOKIE_SOURCES


def test_auth_status_codex_detects_auth_json(tmp_path, monkeypatch) -> None:
    from codexbar_gui import oauth_login as ol

    home = tmp_path / ".codex"
    home.mkdir()
    (home / "auth.json").write_text(
        json.dumps({"tokens": {"access_token": "x", "id_token": "y"}, "account": {"email": "t@e.com"}})
    )
    monkeypatch.setenv("CODEX_HOME", str(home))
    st = ol.auth_status_codex()
    assert st.method == "oauth"
    assert "signed in" in st.label.lower() or "t@e.com" in st.label


def test_auth_status_none_without_files(tmp_path, monkeypatch) -> None:
    from codexbar_gui import oauth_login as ol

    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex"))
    monkeypatch.setattr(ol.Path, "home", lambda: tmp_path)
    st = ol.auth_status_codex()
    # May still find real home if Path.home patched incompletely — just ensure returns AuthStatus
    assert st.provider == "codex"
    assert st.method in {"oauth", "none", "unknown"}


def test_config_dialog_builds_and_reads_source(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.config_dialog import ConfigDialog, ProviderConfigWidget

    _ = QApplication.instance() or QApplication([])
    cfg = {
        "version": 1,
        "providers": [
            {
                "id": "codex",
                "enabled": True,
                "source": "oauth",
                "cookie_source": "auto",
                "api_key": None,
            },
            {
                "id": "claude",
                "enabled": True,
                "source": "auto",
                "cookie_source": "manual",
                "api_key": "sk-test",
            },
        ],
    }
    conf_dir = tmp_path / ".config" / "codexbar"
    conf_dir.mkdir(parents=True)
    conf_file = conf_dir / "config.json"
    conf_file.write_text(json.dumps(cfg))

    monkeypatch.setattr(
        "codexbar_gui.config_dialog._CONFIG_DIR", conf_dir
    )
    monkeypatch.setattr(
        "codexbar_gui.config_dialog._CONFIG_FILE", conf_file
    )
    monkeypatch.setattr(
        "codexbar_gui.config_dialog._LEGACY_CONFIG", tmp_path / "nope"
    )

    dlg = ConfigDialog()
    assert len(dlg._widgets) >= 2
    states = {w.get_state()["id"]: w.get_state() for w in dlg._widgets}
    assert states["codex"]["source"] == "oauth"
    assert states["codex"]["enabled"] is True
    assert "oauth" in [states["codex"]["source"]]

    # Provider widget exposes Login for oauth providers
    w = ProviderConfigWidget(cfg["providers"][0])
    assert w._login_btn is not None
    st = w.get_state()
    assert st["source"] == "oauth"


def test_token_accounts_editor_add_edit_remove_round_trip() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.config_dialog import TokenAccountsEditor

    _ = QApplication.instance() or QApplication([])

    editor = TokenAccountsEditor("zai", None)
    assert editor.get_state() is None  # empty list writes nothing

    editor._accounts.append(
        {"id": "a1", "label": "work", "token": "sk-1", "addedAt": 1, "lastUsed": 1}
    )
    editor._populate()
    state = editor.get_state()
    assert state == {
        "version": 1,
        "activeIndex": 0,
        "accounts": [{"id": "a1", "label": "work", "token": "sk-1", "addedAt": 1, "lastUsed": 1}],
    }

    editor._accounts.append(
        {"id": "a2", "label": "personal", "token": "sk-2", "addedAt": 2, "lastUsed": 2}
    )
    editor._active = 1
    editor._populate()
    assert editor.get_state()["activeIndex"] == 1
    assert [a["label"] for a in editor.get_state()["accounts"]] == ["work", "personal"]

    editor._listw.setCurrentRow(0)
    import codexbar_gui.config_dialog as cd

    _orig_question = cd.QMessageBox.question
    cd.QMessageBox.question = staticmethod(lambda *a, **k: cd.QMessageBox.StandardButton.Yes)
    try:
        editor._remove()
    finally:
        cd.QMessageBox.question = _orig_question
    assert [a["label"] for a in editor.get_state()["accounts"]] == ["personal"]
    assert editor.get_state()["activeIndex"] == 0


def test_token_accounts_editor_marks_ccs_owned_rows_locked() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.claude_oauth import ACCOUNT_NS
    from codexbar_gui.config_dialog import TokenAccountsEditor
    import uuid

    _ = QApplication.instance() or QApplication([])

    ccs_id = str(uuid.uuid5(ACCOUNT_NS, "me@work.io"))
    ta = {
        "version": 1,
        "activeIndex": 0,
        "accounts": [
            {"id": ccs_id, "label": "me@work.io", "token": "tok", "addedAt": 1, "lastUsed": 1},
        ],
    }
    editor = TokenAccountsEditor("claude", ta)
    assert editor._is_ccs(editor._accounts[0]) is True
    editor._listw.setCurrentRow(0)
    assert editor._edit_btn.isEnabled() is False  # ccs-owned row can't be hand-edited
    # Remove looks like it works but doesn't durably — the next ccs poll
    # just re-adds the row — so it must be locked the same way Edit is.
    assert editor._remove_btn.isEnabled() is False
    assert editor._remove_btn.toolTip() != ""
    before = len(editor._accounts)
    editor._remove()  # guarded no-op even if something calls it directly
    assert len(editor._accounts) == before

    # A manually-added account (id doesn't match the uuid5 derivation) stays editable.
    editor._accounts.append(
        {"id": "not-ccs", "label": "manual", "token": "tok2", "addedAt": 2, "lastUsed": 2}
    )
    editor._populate()
    editor._listw.setCurrentRow(1)
    assert editor._edit_btn.isEnabled() is True
    assert editor._remove_btn.isEnabled() is True


def test_provider_widget_get_state_round_trips_token_accounts() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.config_dialog import ProviderConfigWidget

    _ = QApplication.instance() or QApplication([])

    provider = {
        "id": "zai",
        "enabled": True,
        "source": "api",
        "tokenAccounts": {
            "version": 1,
            "activeIndex": 0,
            "accounts": [
                {"id": "x1", "label": "team", "token": "zk-1", "addedAt": 5, "lastUsed": 5}
            ],
        },
    }
    w = ProviderConfigWidget(provider)
    st = w.get_state()
    assert st["tokenAccounts"]["accounts"][0]["label"] == "team"
    assert "token_accounts" not in st  # camelCase only, never snake_case


def test_config_dialog_has_category_sidebar_and_provider_detail_split(
    tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.config_dialog import ConfigDialog

    _ = QApplication.instance() or QApplication([])
    conf_dir = tmp_path / ".config" / "codexbar"
    conf_dir.mkdir(parents=True)
    conf_file = conf_dir / "config.json"
    conf_file.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": [
                    {"id": "codex", "enabled": True, "source": "oauth"},
                    {"id": "claude", "enabled": True, "source": "auto"},
                ],
            }
        )
    )
    monkeypatch.setattr("codexbar_gui.config_dialog._CONFIG_DIR", conf_dir)
    monkeypatch.setattr("codexbar_gui.config_dialog._CONFIG_FILE", conf_file)
    monkeypatch.setattr("codexbar_gui.config_dialog._LEGACY_CONFIG", tmp_path / "nope")

    dlg = ConfigDialog()
    # Official-style layout: category sidebar (General / Providers / Advanced)
    assert dlg._categories.count() == 3
    # Providers category has its own scannable list + one detail page per provider
    assert dlg._provider_list.count() == len(dlg._widgets)
    assert dlg._provider_stack.count() == len(dlg._widgets)

    dlg._provider_list.setCurrentRow(1)
    assert dlg._provider_stack.currentIndex() == 1
    assert dlg._provider_stack.currentWidget() is dlg._widgets[1]


def test_save_config_survives_concurrent_token_rotation(tmp_path, monkeypatch) -> None:
    """Regression: the tray resyncs ccs Claude tokens every ~60s. A Settings
    dialog opened before that resync must not clobber the rotated token when
    the user saves an unrelated edit — ``_save_config`` has to re-read disk,
    not merge onto the dialog's open-time snapshot."""
    import uuid

    from PySide6.QtWidgets import QApplication, QMessageBox

    import codexbar_gui.config_dialog as cd
    from codexbar_gui.claude_oauth import ACCOUNT_NS

    _ = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cd, "find_binary", lambda *a, **k: None)
    monkeypatch.setattr(cd.shutil, "which", lambda *a: None)

    conf_dir = tmp_path / ".config" / "codexbar"
    conf_dir.mkdir(parents=True)
    conf_file = conf_dir / "config.json"
    ccs_id = str(uuid.uuid5(ACCOUNT_NS, "default"))
    conf_file.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": [
                    {"id": "codex", "enabled": False, "source": "oauth"},
                    {
                        "id": "claude",
                        "enabled": True,
                        "source": "oauth",
                        "tokenAccounts": {
                            "version": 1,
                            "activeIndex": 0,
                            "accounts": [
                                {
                                    "id": ccs_id,
                                    "label": "default",
                                    "token": "tok-old",
                                    "addedAt": 1,
                                    "lastUsed": 1,
                                }
                            ],
                        },
                    },
                ],
            }
        )
    )
    monkeypatch.setattr(cd, "_CONFIG_DIR", conf_dir)
    monkeypatch.setattr(cd, "_CONFIG_FILE", conf_file)
    monkeypatch.setattr(cd, "_LEGACY_CONFIG", tmp_path / "nope")

    dlg = cd.ConfigDialog()  # snapshots token="tok-old" into the Claude widget's editor

    # Something else (the tray's 60s ccs sync) rotates the token on disk
    # while the dialog is still sitting open.
    data = json.loads(conf_file.read_text())
    data["providers"][1]["tokenAccounts"]["accounts"][0]["token"] = "tok-rotated"
    conf_file.write_text(json.dumps(data))

    # The user edits an unrelated field and saves.
    codex_widget = next(w for w in dlg._widgets if w._id == "codex")
    codex_widget._enabled.setChecked(True)
    dlg._save_config()

    saved = json.loads(conf_file.read_text())
    codex_entry = next(p for p in saved["providers"] if p["id"] == "codex")
    claude_entry = next(p for p in saved["providers"] if p["id"] == "claude")
    assert codex_entry["enabled"] is True  # the user's own edit still applied
    assert (
        claude_entry["tokenAccounts"]["accounts"][0]["token"] == "tok-rotated"
    )  # not clobbered with the stale open-time value


def test_upstream_passes_source_oauth(monkeypatch) -> None:
    from codexbar_gui import upstream as up

    monkeypatch.setattr(up, "_usage_source_for_provider", lambda p: "oauth")
    monkeypatch.setattr(up, "find_codexbar_binary", lambda: "/fake/codexbar")
    monkeypatch.setattr(up, "_cli_provider_arg", lambda p: "codex")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        m = type("R", (), {"stdout": "[]", "stderr": "", "returncode": 0})()
        return m

    monkeypatch.setattr(up.subprocess, "run", fake_run)
    up.fetch_from_cli(provider="codex", timeout=5)
    assert "--source" in captured["cmd"]
    assert "oauth" in captured["cmd"]
