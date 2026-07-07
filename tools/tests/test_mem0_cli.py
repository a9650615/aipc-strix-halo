from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from aipc_lib import cli


class _Result:
    fetched = 2
    imported = 0


def test_mem0_migrate_cli_defaults_to_dry_run_and_hides_key(tmp_path, monkeypatch):
    key_file = tmp_path / "key.txt"
    key_file.write_text("m0-super-secret\n")
    seen = {}

    def fake_read_api_key(path):
        seen["path"] = path
        return "m0-super-secret"

    def fake_migrate(api_key, **kwargs):
        seen.update(kwargs)
        assert api_key == "m0-super-secret"
        return _Result()

    monkeypatch.setattr(cli.mem0_migrate_mod, "read_api_key", fake_read_api_key)
    monkeypatch.setattr(cli.mem0_migrate_mod, "migrate_from_saas", fake_migrate)

    result = CliRunner().invoke(cli.main, ["mem0", "migrate-from-saas", "--key-file", str(key_file)])

    assert result.exit_code == 0
    assert seen["path"] == key_file
    assert seen["apply"] is False
    assert "m0-super-secret" not in result.output
    assert "dry-run" in result.output


def test_mem0_migrate_cli_apply_writes_local(tmp_path, monkeypatch):
    key_file = tmp_path / "key.txt"
    key_file.write_text("m0-secret\n")

    class Applied:
        fetched = 2
        imported = 2

    seen = {}
    monkeypatch.setattr(cli.mem0_migrate_mod, "read_api_key", lambda path: "m0-secret")

    def fake_migrate(api_key, **kwargs):
        seen.update(kwargs)
        return Applied()

    monkeypatch.setattr(cli.mem0_migrate_mod, "migrate_from_saas", fake_migrate)

    result = CliRunner().invoke(
        cli.main,
        ["mem0", "migrate-from-saas", "--key-file", str(key_file), "--apply"],
    )

    assert result.exit_code == 0
    assert seen["apply"] is True
    assert "imported 2/2" in result.output


def test_config_tools_mem0_local_rewrites_claude_plugin(monkeypatch):
    monkeypatch.setattr(
        cli.mem0_local_mcp_mod,
        "point_claude_plugin",
        lambda: [Path("/tmp/.claude/plugins/cache/mem0-plugins/mem0/0.2.12/.mcp.json")],
    )

    result = CliRunner().invoke(cli.main, ["config", "tools", "--mem0-local"])

    assert result.exit_code == 0
    assert "configured /tmp/.claude/plugins/cache/mem0-plugins/mem0/0.2.12/.mcp.json" in result.output
    assert "Restart Claude Code" in result.output


def test_config_tools_mem0_local_reports_failure(monkeypatch):
    def fail():
        raise cli.mem0_local_mcp_mod.Mem0LocalMcpError("boom")

    monkeypatch.setattr(cli.mem0_local_mcp_mod, "point_claude_plugin", fail)

    result = CliRunner().invoke(cli.main, ["config", "tools", "--mem0-local"])

    assert result.exit_code == 1
    assert "mem0-local failed: boom" in result.output


def test_config_tools_no_tui_offers_configured_reapply_tool(monkeypatch):
    calls = 0
    tool = cli.tools_menu_mod.Tool(
        "mem0 local service",
        lambda: True,
        lambda: None,
        lambda: _mark_called(),
        install_label="Configure Claude",
        uninstall_label="Re-apply Claude",
        uninstall_marks_absent=False,
    )

    def _mark_called():
        nonlocal calls
        calls += 1
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr(cli.tools_menu_mod, "CATEGORIES", {"AI coding tools": [tool]})

    result = CliRunner().invoke(cli.main, ["config", "tools", "--no-tui"], input="y\n")

    assert result.exit_code == 0
    assert calls == 1
    assert "Re-apply Claude mem0 local service?" in result.output
