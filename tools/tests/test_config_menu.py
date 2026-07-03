from __future__ import annotations

from pathlib import Path

import pytest

from aipc_lib import config_menu


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    (tmp_path / ".config" / "goose").mkdir(parents=True)
    (tmp_path / ".aider.conf.yml").write_text(
        "openai-api-base: http://127.0.0.1:4000\nmodel: openai/coder-strong\n"
    )
    (tmp_path / ".config" / "goose" / "profiles.yaml").write_text(
        "default:\n  provider: openai\n  processor: coder-strong\n"
        "  accelerator: coder-fast\n  host: http://127.0.0.1:4000\n"
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
    assert config_menu.current_tier(path) == "coder-strong"


def test_set_tier_replaces_first_occurrence_only(home: Path) -> None:
    path = home / ".config" / "goose" / "profiles.yaml"
    changed = config_menu.set_tier(path, "coder-thinking")
    assert changed is True
    text = path.read_text()
    # processor (first match) becomes coder-thinking; accelerator
    # (coder-fast, unrelated, always meant to stay fast) is untouched.
    assert "processor: coder-thinking" in text
    assert "accelerator: coder-fast" in text


def test_set_tier_returns_false_when_no_tier_field_present(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("no tier field here\n")
    assert config_menu.set_tier(path, "coder-fast") is False
