"""GUI-module tests: official codexbar only (no Python usage port)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_find_codexbar_binary_helpers() -> None:
    from codexbar_gui.upstream import find_codexbar_binary
    from codexbar_gui.server_launcher import _find_cli

    # May be None in bare CI; on this AI PC usually ~/.local/bin/codexbar
    binary = find_codexbar_binary()
    cli = _find_cli()
    if binary:
        assert cli == [binary]
        assert Path(binary).is_file()
    else:
        assert cli == []


def test_serve_cmd_requires_official_binary() -> None:
    from codexbar_gui.server_launcher import _serve_cmd
    from codexbar_gui.upstream import find_codexbar_binary

    cmd = _serve_cmd(8080)
    binary = find_codexbar_binary()
    if binary:
        assert cmd == [binary, "serve", "--port", "8080"]
    else:
        assert cmd is None


def test_parse_and_summary_without_network() -> None:
    from codexbar_gui.upstream import parse_upstream_list
    from codexbar_gui.usage_panel import summary_from_views

    views = parse_upstream_list(
        [
            {
                "provider": "codex",
                "source": "oauth",
                "usage": {
                    "primary": {
                        "usedPercent": 40,
                        "windowMinutes": 300,
                        "resetDescription": "in 1h",
                    },
                    "secondary": {"usedPercent": 80, "windowMinutes": 10080},
                },
                "pace": {"primary": {"summary": "on pace"}},
            }
        ]
    )
    used, tip = summary_from_views(views)
    assert used == 40
    assert "Codex" in tip or "codex" in tip.lower()


@pytest.mark.skipif(
    os.environ.get("CODEXBAR_LIVE") != "1",
    reason="set CODEXBAR_LIVE=1 to hit real codexbar CLI",
)
def test_live_official_cli() -> None:
    from codexbar_gui.upstream import fetch_from_cli, find_codexbar_binary

    assert find_codexbar_binary()
    views = fetch_from_cli()
    assert views is not None
    assert len(views) >= 1
