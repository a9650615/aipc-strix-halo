from __future__ import annotations

from unittest.mock import patch

from aipc_lib import tools_menu


def test_categories_cover_expected_groups() -> None:
    assert set(tools_menu.CATEGORIES.keys()) == {"AI coding tools", "Terminal"}


def test_ai_coding_tools_category_has_all_tools() -> None:
    names = [t.name for t in tools_menu.CATEGORIES["AI coding tools"]]
    assert names == [
        "aider",
        "cline (VSCode)",
        "continue (VSCode)",
        "goose",
        "opencode",
        "mem0 local service",
        "codexbar usage (aipc-usage)",
        "codexbar GUI",
    ]


def test_terminal_category_has_ccstatus() -> None:
    names = [t.name for t in tools_menu.CATEGORIES["Terminal"]]
    assert names == ["ccstatus"]


def test_mem0_local_tool_is_service_config_action() -> None:
    tool = next(t for t in tools_menu.CATEGORIES["AI coding tools"] if t.name == "mem0 local service")
    assert tool.install_label == "Configure Claude"
    assert tool.uninstall_label == "Re-apply Claude"
    assert tool.uninstall_marks_absent is False


def test_has_returns_false_for_nonexistent_command() -> None:
    assert tools_menu._has("this-command-does-not-exist-xyz") is False


def test_has_returns_true_for_real_command() -> None:
    assert tools_menu._has("sh") is True


def test_vscode_ext_installed_false_when_code_missing() -> None:
    with patch("aipc_lib.tools_menu._has", return_value=False):
        assert tools_menu._vscode_ext_installed("some.extension") is False


def test_vscode_ext_installed_checks_list_extensions_output() -> None:
    fake_proc = type("P", (), {"stdout": "saoudrizwan.claude-dev\nfoo.bar\n"})()
    with (
        patch("aipc_lib.tools_menu._has", return_value=True),
        patch("subprocess.run", return_value=fake_proc),
    ):
        assert tools_menu._vscode_ext_installed("saoudrizwan.claude-dev") is True
        assert tools_menu._vscode_ext_installed("nonexistent.ext") is False


def test_every_tool_is_installed_check_is_callable_and_boolean() -> None:
    # Smoke test on this real machine — every check must run without
    # raising and return an actual bool, whatever the real installed state.
    for tools in tools_menu.CATEGORIES.values():
        for tool in tools:
            result = tool.is_installed()
            assert isinstance(result, bool)


def test_every_tool_has_an_uninstall_callable() -> None:
    # Not run here (would actually remove things on this machine) — just
    # confirms the modularity contract (install implies a matching removal
    # path) holds for every entry, so none can be added install-only.
    for tools in tools_menu.CATEGORIES.values():
        for tool in tools:
            assert callable(tool.uninstall)
