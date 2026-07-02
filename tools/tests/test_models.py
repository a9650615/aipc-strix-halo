from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from aipc_lib import models


@pytest.fixture()
def manifest(tmp_path: Path) -> Path:
    # Mirrors the real schema shipped in
    # modules/llm-models/files/etc/aipc/models/models.yaml: alias, backend,
    # model_id, size_gb only — there is no on-disk `path` field.
    p = tmp_path / "models.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            models:
              - alias: router-1b
                backend: lemonade
                model_id: amd/Llama-3.2-1B
                size_gb: 2
              - alias: main-70b
                backend: ollama
                model_id: llama3.3:70b
                size_gb: 40
              - alias: main-cloud
                backend: anthropic
                model_id: anthropic/claude-sonnet-4-6
                size_gb: cloud
            """
        )
    )
    return p


def test_load_manifest_returns_entries(manifest: Path) -> None:
    entries = models.load_manifest(manifest)
    assert [e.alias for e in entries] == ["router-1b", "main-70b", "main-cloud"]
    assert entries[0].backend == "lemonade"
    assert entries[1].size_gb == 40
    assert entries[2].size_gb == "cloud"


def test_load_manifest_missing_file_returns_empty(tmp_path: Path) -> None:
    assert models.load_manifest(tmp_path / "nope.yaml") == []


def test_load_manifest_invalid_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(": not: valid: yaml: [[")
    with pytest.raises(yaml.YAMLError):
        models.load_manifest(bad)


def test_is_cloud_true_for_remote_backends() -> None:
    entry = models.ModelEntry(alias="main-cloud", backend="anthropic", model_id="x", size_gb="cloud")
    assert entry.is_cloud is True


def test_is_cloud_false_for_local_backends() -> None:
    entry = models.ModelEntry(alias="main-70b", backend="ollama", model_id="x", size_gb=40)
    assert entry.is_cloud is False


def test_on_disk_status_present(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entry = models.ModelEntry(alias="router-1b", backend="lemonade", model_id="x", size_gb=1)
    entry.weights_path(root).mkdir(parents=True)
    assert models.on_disk_status(entry, root) == "present"


def test_on_disk_status_missing(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    entry = models.ModelEntry(alias="router-1b", backend="lemonade", model_id="x", size_gb=1)
    assert models.on_disk_status(entry, root) == "missing"


def test_on_disk_status_cloud_backend_is_not_applicable(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entry = models.ModelEntry(alias="main-cloud", backend="anthropic", model_id="x", size_gb="cloud")
    assert models.on_disk_status(entry, root) == "n/a"


def test_sync_check_all_present(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = models.load_manifest(manifest)
    for e in entries:
        if not e.is_cloud:
            e.weights_path(root).mkdir(parents=True)
    assert models.sync_check(entries, root) == []


def test_sync_check_reports_missing(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = models.load_manifest(manifest)
    entries[0].weights_path(root).mkdir(parents=True)  # router-1b present
    missing = models.sync_check(entries, root)
    assert [m.alias for m in missing] == ["main-70b"]


def test_sync_check_excludes_cloud_backends(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = models.load_manifest(manifest)
    for e in entries:
        if not e.is_cloud:
            e.weights_path(root).mkdir(parents=True)
    # main-cloud never appears in sync_check even though nothing was created for it
    assert models.sync_check(entries, root) == []


def test_sync_check_empty_manifest(tmp_path: Path) -> None:
    assert models.sync_check([], tmp_path / "models") == []


def test_pull_command_ollama() -> None:
    entry = models.ModelEntry(alias="main-70b", backend="ollama", model_id="llama3.3:70b", size_gb=40)
    assert models.pull_command(entry) == ["ollama", "pull", "llama3.3:70b"]


def test_pull_command_lemonade() -> None:
    entry = models.ModelEntry(alias="router-1b", backend="lemonade", model_id="amd/Llama-3.2-1B", size_gb=2)
    assert models.pull_command(entry) == ["lemonade-server", "pull", "amd/Llama-3.2-1B"]


def test_pull_command_cloud_backend_is_none() -> None:
    entry = models.ModelEntry(alias="main-cloud", backend="anthropic", model_id="x", size_gb="cloud")
    assert models.pull_command(entry) is None


class _FakeCompletedProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_sync_pull_invokes_backend_command_and_marks_present(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = [models.ModelEntry(alias="main-70b", backend="ollama", model_id="llama3.3:70b", size_gb=40)]

    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    results = models.sync_pull(entries, root, runner=fake_runner)

    assert calls == [["ollama", "pull", "llama3.3:70b"]]
    assert results == [(entries[0], True)]
    assert models.on_disk_status(entries[0], root) == "present"


def test_sync_pull_reports_failure_without_marking_present(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = [models.ModelEntry(alias="main-70b", backend="ollama", model_id="llama3.3:70b", size_gb=40)]

    def failing_runner(cmd, **kwargs):
        return _FakeCompletedProcess(1)

    results = models.sync_pull(entries, root, runner=failing_runner)

    assert results == [(entries[0], False)]
    assert models.on_disk_status(entries[0], root) == "missing"


def test_sync_pull_skips_cloud_backends_without_calling_runner(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = [models.ModelEntry(alias="main-cloud", backend="anthropic", model_id="x", size_gb="cloud")]

    def runner_should_not_be_called(cmd, **kwargs):
        raise AssertionError("runner must not be called for cloud backends")

    results = models.sync_pull(entries, root, runner=runner_should_not_be_called)
    assert results == []


def test_sync_pull_skips_already_present_entries(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entry = models.ModelEntry(alias="main-70b", backend="ollama", model_id="llama3.3:70b", size_gb=40)
    entry.weights_path(root).mkdir(parents=True)

    def runner_should_not_be_called(cmd, **kwargs):
        raise AssertionError("runner must not be called for already-present entries")

    results = models.sync_pull([entry], root, runner=runner_should_not_be_called)
    assert results == []
