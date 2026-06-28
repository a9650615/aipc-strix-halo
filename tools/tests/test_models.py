from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from aipc_lib import models


@pytest.fixture()
def manifest(tmp_path: Path) -> Path:
    p = tmp_path / "models.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            models:
              - alias: router-1b
                backend: lemonade
                model_id: amd/Llama-3.2-1B
                size_gb: 2
                path: lemonade/router-1b
              - alias: main-70b
                backend: ollama
                model_id: llama3.3:70b
                size_gb: 40
                path: ollama/main-70b
            """
        )
    )
    return p


def test_load_manifest_returns_entries(manifest: Path) -> None:
    entries = models.load_manifest(manifest)
    assert [e.alias for e in entries] == ["router-1b", "main-70b"]
    assert entries[0].backend == "lemonade"
    assert entries[1].size_gb == 40


def test_load_manifest_missing_file_returns_empty(tmp_path: Path) -> None:
    assert models.load_manifest(tmp_path / "nope.yaml") == []


def test_load_manifest_invalid_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(": not: valid: yaml: [[")
    with pytest.raises(yaml.YAMLError):
        models.load_manifest(bad)


def test_on_disk_status_present(tmp_path: Path) -> None:
    root = tmp_path / "models"
    (root / "lemonade" / "router-1b").mkdir(parents=True)
    entry = models.ModelEntry(
        alias="router-1b",
        backend="lemonade",
        model_id="x",
        size_gb=1,
        path="lemonade/router-1b",
    )
    assert models.on_disk_status(entry, root) == "present"


def test_on_disk_status_missing(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    entry = models.ModelEntry(
        alias="router-1b",
        backend="lemonade",
        model_id="x",
        size_gb=1,
        path="lemonade/router-1b",
    )
    assert models.on_disk_status(entry, root) == "missing"


def test_sync_check_all_present(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    (root / "lemonade" / "router-1b").mkdir(parents=True)
    (root / "ollama" / "main-70b").mkdir(parents=True)
    entries = models.load_manifest(manifest)
    assert models.sync_check(entries, root) == []


def test_sync_check_reports_missing(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    (root / "lemonade" / "router-1b").mkdir(parents=True)
    entries = models.load_manifest(manifest)
    missing = models.sync_check(entries, root)
    assert [m.alias for m in missing] == ["main-70b"]


def test_sync_check_empty_manifest(tmp_path: Path) -> None:
    assert models.sync_check([], tmp_path / "models") == []
