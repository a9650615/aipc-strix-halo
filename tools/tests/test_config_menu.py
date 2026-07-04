from __future__ import annotations

from pathlib import Path

import pytest

from aipc_lib import config_menu


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    (tmp_path / ".config" / "goose").mkdir(parents=True)
    (tmp_path / ".aider.conf.yml").write_text(
        "openai-api-base: http://127.0.0.1:4000\nmodel: openai/ornith-35b\n"
    )
    (tmp_path / ".config" / "goose" / "profiles.yaml").write_text(
        "default:\n  provider: openai\n  processor: ornith-35b\n"
        "  accelerator: coder-agentic\n  host: http://127.0.0.1:4000\n"
    )
    return tmp_path


def test_installed_configs_only_returns_existing_files(home: Path) -> None:
    found = config_menu.installed_configs(home)
    tools = sorted(tc.tool for tc, _ in found)
    assert tools == ["aider", "goose"]


def test_installed_configs_skips_missing_cline(home: Path) -> None:
    found = config_menu.installed_configs(home)
    assert all(tc.tool != "cline" for tc, _ in found)


def test_current_tier_reads_first_match(home: Path) -> None:
    path = home / ".aider.conf.yml"
    assert config_menu.current_tier(path) == "ornith-35b"


def test_set_tier_replaces_first_occurrence_only(home: Path) -> None:
    path = home / ".config" / "goose" / "profiles.yaml"
    changed = config_menu.set_tier(path, "coder-agentic")
    assert changed is True
    text = path.read_text()
    # processor (first match) becomes coder-agentic; accelerator (already
    # coder-agentic, unrelated field) is left as-is by the count=1 subn —
    # only the first regex match in the file is ever touched.
    assert text.count("processor: coder-agentic") == 1
    assert text.count("accelerator: coder-agentic") == 1


def test_set_tier_returns_false_when_no_tier_field_present(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("no tier field here\n")
    assert config_menu.set_tier(path, "coder-agentic") is False
