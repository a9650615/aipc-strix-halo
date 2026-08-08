"""Claude OAuth bridge: ccs credential discovery + refresh write-back (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI))

from codexbar_gui import claude_oauth

NOW = 1_800_000_000_000


def _write(path: Path, access: str, refresh: str, expires_at: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pluginSecrets": {"keep": "me"},
                "claudeAiOauth": {
                    "accessToken": access,
                    "refreshToken": refresh,
                    "expiresAt": expires_at,
                },
            }
        )
    )


def _home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_blank_shared_file_falls_back_to_ccs_instance(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    _write(home / ".claude" / ".credentials.json", "", "", 0)
    _write(home / ".ccs" / "instances" / "work" / ".credentials.json", "live", "r1", NOW + 600_000)

    assert claude_oauth.access_token(now_ms=NOW) == "live"


def test_expired_token_refreshes_and_writes_back(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    creds = home / ".ccs" / "instances" / "work" / ".credentials.json"
    _write(creds, "stale", "r1", NOW - 1000)

    monkeypatch.setattr(
        claude_oauth,
        "_post_refresh",
        lambda token: {"access_token": "fresh", "refresh_token": "r2", "expires_in": 28800},
    )
    claude_oauth._last_refresh_fail = 0.0

    assert claude_oauth.access_token(now_ms=NOW) == "fresh"

    data = json.loads(creds.read_text())
    assert data["claudeAiOauth"]["accessToken"] == "fresh"
    # Rotated refresh token must land on disk or Claude Code loses its login
    assert data["claudeAiOauth"]["refreshToken"] == "r2"
    assert data["claudeAiOauth"]["expiresAt"] == NOW + 28_800_000
    assert data["pluginSecrets"] == {"keep": "me"}
    assert creds.stat().st_mode & 0o777 == 0o600


def test_refresh_failure_keeps_file_and_reports_stale_token(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    creds = home / ".ccs" / "instances" / "work" / ".credentials.json"
    _write(creds, "stale", "r1", NOW - 1000)

    monkeypatch.setattr(claude_oauth, "_post_refresh", lambda token: None)
    claude_oauth._last_refresh_fail = 0.0

    # Expired but present: hand it over anyway — the API decides, not our clock
    assert claude_oauth.access_token(now_ms=NOW) == "stale"
    assert json.loads(creds.read_text())["claudeAiOauth"]["refreshToken"] == "r1"


def test_fresher_instance_wins(monkeypatch, tmp_path) -> None:
    home = _home(monkeypatch, tmp_path)
    _write(home / ".ccs" / "instances" / "a" / ".credentials.json", "old", "r1", NOW + 200_000)
    _write(home / ".ccs" / "instances" / "b" / ".credentials.json", "new", "r2", NOW + 900_000)

    assert claude_oauth.access_token(now_ms=NOW) == "new"


def test_is_ccs_owned_is_case_insensitive() -> None:
    """The official (Swift) CLI reformats UUIDs to uppercase when it rewrites
    config.json (observed on the live machine after ``codexbar config
    validate``); ``uuid5`` always renders lowercase. A ccs-synced row must
    still be recognized as ccs-owned regardless of which case is on disk —
    otherwise the sync would treat its own rows as user-owned and stop
    refreshing their tokens."""
    import uuid

    label = "a9650615@gmail.com"
    lower_id = str(uuid.uuid5(claude_oauth.ACCOUNT_NS, label))
    upper_id = lower_id.upper()

    assert claude_oauth.is_ccs_owned({"id": lower_id, "label": label}) is True
    assert claude_oauth.is_ccs_owned({"id": upper_id, "label": label}) is True
    assert claude_oauth.is_ccs_owned({"id": "not-a-match", "label": label}) is False


def test_sync_recognizes_uppercase_ids_from_official_cli(monkeypatch, tmp_path) -> None:
    """Regression: a ccs row whose id was uppercased by ``codexbar config
    validate`` must still get its token refreshed on the next sync, not be
    frozen in place as if it were user-owned."""
    import uuid

    home = _home(monkeypatch, tmp_path)
    _write(home / ".claude" / ".credentials.json", "tok-personal", "r1", NOW + 600_000)
    _write(
        home / ".ccs" / "instances" / "work" / ".credentials.json",
        "tok-work",
        "r2",
        NOW + 600_000,
    )

    cfg_path = home / ".config" / "codexbar" / "config.json"
    cfg_path.parent.mkdir(parents=True)
    upper_id = str(uuid.uuid5(claude_oauth.ACCOUNT_NS, "default")).upper()
    cfg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": [
                    {
                        "id": "claude",
                        "enabled": True,
                        "tokenAccounts": {
                            "version": 1,
                            "activeIndex": 0,
                            "accounts": [
                                {
                                    "id": upper_id,
                                    "label": "default",
                                    "token": "tok-personal-STALE",
                                    "addedAt": 1,
                                    "lastUsed": 1,
                                }
                            ],
                        },
                    }
                ],
            }
        )
    )

    claude_oauth.sync_token_accounts(min_accounts=1)

    entry = next(
        p for p in json.loads(cfg_path.read_text())["providers"] if p["id"] == "claude"
    )
    accounts = entry["tokenAccounts"]["accounts"]
    default = next(a for a in accounts if a["label"] == "default")
    assert default["token"] == "tok-personal"  # refreshed, not frozen as "STALE"


def test_build_cli_env_injects_claude_token(monkeypatch, tmp_path) -> None:
    from codexbar_gui import upstream

    home = _home(monkeypatch, tmp_path)
    _write(home / ".ccs" / "instances" / "work" / ".credentials.json", "live", "r1", NOW + 600_000)
    monkeypatch.setattr(claude_oauth, "access_token", lambda now_ms=None: "live")

    env = upstream.build_cli_env("claude", base={}, data={"providers": []})
    assert env["CODEXBAR_CLAUDE_OAUTH_TOKEN"] == "live"

    # Never clobber an explicit env token
    env2 = upstream.build_cli_env("claude", base={"CODEXBAR_CLAUDE_OAUTH_TOKEN": "mine"}, data={})
    assert env2["CODEXBAR_CLAUDE_OAUTH_TOKEN"] == "mine"

    # Other providers untouched
    env3 = upstream.build_cli_env("codex", base={}, data={"providers": []})
    assert "CODEXBAR_CLAUDE_OAUTH_TOKEN" not in env3
