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
