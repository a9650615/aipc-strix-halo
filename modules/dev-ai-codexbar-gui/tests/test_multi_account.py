"""Multi-account support: ccs profiles → official ``tokenAccounts`` → per-account cards."""

from __future__ import annotations

import json
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI))

from codexbar_gui import claude_oauth, menu_bar, upstream

NOW = 1_800_000_000_000


def _home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEXBAR_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _login(path: Path, access: str, email: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": access,
                    "refreshToken": "r-" + access,
                    "expiresAt": NOW + 600_000,
                }
            }
        )
    )
    if email:
        path.with_name(".claude.json").write_text(
            json.dumps({"oauthAccount": {"emailAddress": email}})
        )


def _cfg(home: Path) -> Path:
    return home / ".config" / "codexbar" / "config.json"


def test_two_profiles_sync_into_official_token_accounts(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    _login(home / ".claude" / ".credentials.json", "tok-personal")
    _login(home / ".ccs" / "instances" / "work" / ".credentials.json", "tok-work", "me@work.io")

    labels = claude_oauth.sync_token_accounts()
    assert labels == ["default", "me@work.io"]

    entry = next(
        p for p in json.loads(_cfg(home).read_text())["providers"] if p["id"] == "claude"
    )
    # camelCase only — the CLI ignores a snake_case token_accounts block
    accounts = entry["tokenAccounts"]["accounts"]
    assert [a["label"] for a in accounts] == ["default", "me@work.io"]
    assert [a["token"] for a in accounts] == ["tok-personal", "tok-work"]
    assert entry["tokenAccounts"]["version"] == 1
    assert _cfg(home).stat().st_mode & 0o777 == 0o600
    assert upstream.token_account_labels("claude") == ["default", "me@work.io"]


def test_sync_is_stable_and_keeps_other_config(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    _cfg(home).parent.mkdir(parents=True, exist_ok=True)
    _cfg(home).write_text(
        json.dumps(
            {
                "version": 1,
                "providers": [
                    {"id": "codex", "enabled": True, "api_key": "keep-me"},
                    {"id": "claude", "enabled": True, "source": "oauth"},
                ],
                "gui": {"language": "zh-Hant"},
            }
        )
    )
    _login(home / ".claude" / ".credentials.json", "a1")
    _login(home / ".ccs" / "instances" / "work" / ".credentials.json", "b1", "me@work.io")

    claude_oauth.sync_token_accounts()
    first = json.loads(_cfg(home).read_text())
    ids = [a["id"] for a in first["providers"][1]["tokenAccounts"]["accounts"]]
    added = [a["addedAt"] for a in first["providers"][1]["tokenAccounts"]["accounts"]]

    _login(home / ".ccs" / "instances" / "work" / ".credentials.json", "b2", "me@work.io")
    claude_oauth.sync_token_accounts()
    second = json.loads(_cfg(home).read_text())
    entry = second["providers"][1]

    assert [a["id"] for a in entry["tokenAccounts"]["accounts"]] == ids
    assert [a["addedAt"] for a in entry["tokenAccounts"]["accounts"]] == added
    assert entry["tokenAccounts"]["accounts"][1]["token"] == "b2"
    assert entry["source"] == "oauth"
    assert second["providers"][0]["api_key"] == "keep-me"
    assert second["gui"] == {"language": "zh-Hant"}


def test_single_profile_keeps_ambient_oauth_path(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    _login(home / ".claude" / ".credentials.json", "only")

    assert claude_oauth.sync_token_accounts() == []
    assert not _cfg(home).exists()
    assert upstream.token_account_labels("claude") == []


def test_cli_gets_all_accounts_and_no_ambient_token(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    _login(home / ".claude" / ".credentials.json", "a")
    _login(home / ".ccs" / "instances" / "work" / ".credentials.json", "b", "me@work.io")
    claude_oauth.sync_token_accounts()

    seen: dict = {}

    class _Proc:
        stdout = json.dumps(
            [
                {"provider": "claude", "account": "default", "usage": {}},
                {"provider": "claude", "account": "me@work.io", "usage": {}},
            ]
        )
        stderr = ""

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        seen["env"] = kw.get("env") or {}
        return _Proc()

    monkeypatch.setattr(upstream, "find_codexbar_binary", lambda: "/usr/bin/codexbar")
    monkeypatch.setattr(upstream.subprocess, "run", _run)

    views = upstream.fetch_enabled_providers(["claude"], timeout=5.0)

    assert "--all-accounts" in seen["cmd"]
    # tokenAccounts carry the tokens; an ambient one would shadow every account
    assert "CODEXBAR_CLAUDE_OAUTH_TOKEN" not in seen["env"]
    assert [v.account for v in views] == ["default", "me@work.io"]
    assert [v.key for v in views] == ["claude:default", "claude:me@work.io"]


def test_cards_disambiguate_only_when_needed() -> None:
    a = upstream.ProviderView(provider="claude", account="me@home.dev")
    b = upstream.ProviderView(provider="claude", account="me@work.io")
    solo = upstream.ProviderView(provider="codex", account="me@home.dev")
    views = [a, b, solo]

    assert upstream.card_label(a, views) == "Claude · me"
    assert upstream.card_label(b, views) == "Claude · me"
    assert upstream.card_label(solo, views) == "Codex"
    assert upstream.card_label(a, [a]) == "Claude"
    # Tabs/cards are keyed per account, so both stay clickable
    assert a.key != b.key


def test_overview_order_keeps_every_account() -> None:
    a = upstream.ProviderView(provider="claude", account="one@x.io")
    b = upstream.ProviderView(provider="claude", account="two@x.io")
    c = upstream.ProviderView(provider="codex")
    settings = menu_bar.MenuBarSettings(overview_providers=["claude", "codex"])

    assert menu_bar.order_overview_views([c, a, b], settings) == [a, b, c]


def test_sync_preserves_manually_added_account(monkeypatch, tmp_path) -> None:
    """A token account the user added by hand in Settings must survive a resync.

    ``sync_token_accounts`` only owns the rows whose id it derived
    (``uuid5(ACCOUNT_NS, label)``); anything else is user-owned and must keep
    its position and ``addedAt`` even though the whole ``accounts`` list gets
    rebuilt on every sync.
    """
    home = _home(monkeypatch, tmp_path)
    _login(home / ".claude" / ".credentials.json", "tok-personal")
    _login(home / ".ccs" / "instances" / "work" / ".credentials.json", "tok-work", "me@work.io")

    claude_oauth.sync_token_accounts()

    # User hand-adds a third account via the Settings editor: a real (non-ccs)
    # id, sitting between the two ccs-owned rows.
    cfg_path = _cfg(home)
    data = json.loads(cfg_path.read_text())
    entry = next(p for p in data["providers"] if p["id"] == "claude")
    accounts = entry["tokenAccounts"]["accounts"]
    manual = {
        "id": "11111111-2222-3333-4444-555555555555",
        "label": "manual@example.com",
        "token": "sk-ant-oat-manual",
        "addedAt": 1234,
        "lastUsed": 1234,
    }
    accounts.insert(1, manual)
    cfg_path.write_text(json.dumps(data, indent=2))

    claude_oauth.sync_token_accounts()

    after = json.loads(cfg_path.read_text())
    after_entry = next(p for p in after["providers"] if p["id"] == "claude")
    after_accounts = after_entry["tokenAccounts"]["accounts"]

    assert [a["label"] for a in after_accounts] == ["default", "manual@example.com", "me@work.io"]
    manual_after = after_accounts[1]
    assert manual_after == manual  # untouched: id, token, addedAt, lastUsed all survive
    # ccs-owned rows are still refreshed as usual
    assert after_accounts[0]["label"] == "default"
    assert after_accounts[2]["label"] == "me@work.io"

    # Removing the ccs profile drops only the ccs-owned row, never the manual one.
    import shutil

    shutil.rmtree(home / ".ccs" / "instances" / "work")
    claude_oauth.sync_token_accounts(min_accounts=1)
    final = json.loads(cfg_path.read_text())
    final_accounts = next(p for p in final["providers"] if p["id"] == "claude")["tokenAccounts"]["accounts"]
    assert [a["label"] for a in final_accounts] == ["default", "manual@example.com"]


def test_unchanged_tokens_do_not_rewrite_config(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    _login(home / ".claude" / ".credentials.json", "a1")
    _login(home / ".ccs" / "instances" / "work" / ".credentials.json", "b1", "me@work.io")

    claude_oauth.sync_token_accounts()
    stamp = _cfg(home).stat().st_mtime_ns

    assert claude_oauth.sync_token_accounts() == ["default", "me@work.io"]
    assert _cfg(home).stat().st_mtime_ns == stamp

    _login(home / ".ccs" / "instances" / "work" / ".credentials.json", "b2", "me@work.io")
    claude_oauth.sync_token_accounts()
    assert _cfg(home).stat().st_mtime_ns != stamp
