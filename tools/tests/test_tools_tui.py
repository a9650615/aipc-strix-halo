from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from aipc_lib.tools_menu import Tool
from aipc_lib.tools_tui import ToolRow, ToolsApp


def _ok(*_a: object, **_kw: object) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0)


def _fail(*_a: object, **_kw: object) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1)


@pytest.fixture()
def fake_categories() -> dict[str, list[Tool]]:
    return {
        "Test category": [
            Tool("already-there", lambda: True, _ok),
            Tool("not-yet", lambda: False, _ok),
        ]
    }


@pytest.mark.asyncio
async def test_app_renders_one_row_per_tool(fake_categories: dict) -> None:
    with patch("aipc_lib.tools_tui.CATEGORIES", fake_categories):
        app = ToolsApp()
        async with app.run_test() as pilot:
            rows = app.query(ToolRow)
            assert len(rows) == 2


@pytest.mark.asyncio
async def test_already_installed_tool_shows_disabled_button(fake_categories: dict) -> None:
    with patch("aipc_lib.tools_tui.CATEGORIES", fake_categories):
        app = ToolsApp()
        async with app.run_test() as pilot:
            row = next(r for r in app.query(ToolRow) if r.tool.name == "already-there")
            button = row.query_one("Button")
            assert button.disabled is True
            assert str(button.label) == "Installed"


@pytest.mark.asyncio
async def test_not_installed_tool_has_enabled_install_button(fake_categories: dict) -> None:
    with patch("aipc_lib.tools_tui.CATEGORIES", fake_categories):
        app = ToolsApp()
        async with app.run_test() as pilot:
            row = next(r for r in app.query(ToolRow) if r.tool.name == "not-yet")
            button = row.query_one("Button")
            assert button.disabled is False
            assert str(button.label) == "Install"


@pytest.mark.asyncio
async def test_clicking_install_button_runs_install_and_updates_label(fake_categories: dict) -> None:
    with patch("aipc_lib.tools_tui.CATEGORIES", fake_categories):
        app = ToolsApp()
        async with app.run_test() as pilot:
            row = next(r for r in app.query(ToolRow) if r.tool.name == "not-yet")
            button = row.query_one("Button")
            await pilot.click(button)
            # _install runs in a worker thread; give it a moment to finish.
            await pilot.pause()
            for _ in range(20):
                if str(button.label) == "Installed":
                    break
                await pilot.pause(0.05)
            assert str(button.label) == "Installed"
