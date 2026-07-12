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
    # model_id, size_gb, plus optional checkpoints/recipe/label for custom
    # Lemonade registrations — there is no on-disk `path` field.
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


def _mark_synced(entry: models.ModelEntry, root: Path) -> None:
    entry.weights_path(root).mkdir(parents=True, exist_ok=True)
    entry.marker_path(root).write_text(entry.model_id + "\n")


def test_on_disk_status_present(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entry = models.ModelEntry(alias="router-1b", backend="lemonade", model_id="x", size_gb=1)
    _mark_synced(entry, root)
    assert models.on_disk_status(entry, root) == "present"


def test_on_disk_status_stale_when_model_id_changed(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entry = models.ModelEntry(alias="ornith-35b", backend="lemonade", model_id="old-id", size_gb=20)
    _mark_synced(entry, root)
    swapped = models.ModelEntry(alias="ornith-35b", backend="lemonade", model_id="new-id", size_gb=26)
    assert models.on_disk_status(swapped, root) == "stale"


def test_on_disk_status_stale_when_marker_file_absent(tmp_path: Path) -> None:
    # Pre-marker sync layout: alias dir exists but records no model_id.
    root = tmp_path / "models"
    entry = models.ModelEntry(alias="router-1b", backend="lemonade", model_id="x", size_gb=1)
    entry.weights_path(root).mkdir(parents=True)
    assert models.on_disk_status(entry, root) == "stale"


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
            _mark_synced(e, root)
    assert models.sync_check(entries, root) == []


def test_sync_check_reports_missing(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = models.load_manifest(manifest)
    _mark_synced(entries[0], root)  # router-1b present
    missing = models.sync_check(entries, root)
    assert [m.alias for m in missing] == ["main-70b"]


def test_sync_check_includes_stale(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = models.load_manifest(manifest)
    for e in entries:
        if not e.is_cloud:
            _mark_synced(e, root)
    entries[0].marker_path(root).write_text("some-previous-model-id\n")
    assert [m.alias for m in models.sync_check(entries, root)] == ["router-1b"]


def test_sync_check_excludes_cloud_backends(manifest: Path, tmp_path: Path) -> None:
    root = tmp_path / "models"
    entries = models.load_manifest(manifest)
    for e in entries:
        if not e.is_cloud:
            _mark_synced(e, root)
    # main-cloud never appears in sync_check even though nothing was created for it
    assert models.sync_check(entries, root) == []


def test_sync_check_empty_manifest(tmp_path: Path) -> None:
    assert models.sync_check([], tmp_path / "models") == []


def test_pull_command_ollama() -> None:
    entry = models.ModelEntry(alias="main-70b", backend="ollama", model_id="llama3.3:70b", size_gb=40)
    assert models.pull_command(entry) == [
        "sudo",
        "podman",
        "exec",
        "ollama",
        "ollama",
        "pull",
        "llama3.3:70b",
    ]


def test_pull_command_lemonade() -> None:
    entry = models.ModelEntry(alias="router-1b", backend="lemonade", model_id="amd/Llama-3.2-1B", size_gb=2)
    assert models.pull_command(entry) == [
        "sudo",
        "podman",
        "exec",
        "lemonade",
        "/opt/lemonade/lemonade",
        "pull",
        "amd/Llama-3.2-1B",
    ]


def test_pull_command_lemonade_custom_checkpoints() -> None:
    entry = models.ModelEntry(
        alias="ornith-35b",
        backend="lemonade",
        model_id="Ornith-1.0-35B-MTP-APEX-I-Balanced",
        size_gb=26,
        checkpoints={"main": "SC117/Ornith-1.0-35B-MTP-APEX-GGUF:Ornith-1.0-35B-MTP-APEX-I-Balanced.gguf"},
        recipe="llamacpp",
        labels=["tool-calling"],
    )
    assert models.pull_command(entry) == [
        "sudo",
        "podman",
        "exec",
        "lemonade",
        "/opt/lemonade/lemonade",
        "pull",
        "user.Ornith-1.0-35B-MTP-APEX-I-Balanced",
        "--checkpoint",
        "main",
        "SC117/Ornith-1.0-35B-MTP-APEX-GGUF:Ornith-1.0-35B-MTP-APEX-I-Balanced.gguf",
        "--recipe",
        "llamacpp",
        "--label",
        "tool-calling",
    ]


def test_pull_command_lemonade_multi_checkpoint_and_labels() -> None:
    entry = models.ModelEntry.from_dict(
        {
            "alias": "assistant-gemma",
            "backend": "lemonade",
            "model_id": "Gemma4-26B-A4B-QAT-Uncensored-Balanced-Q4_K_M",
            "checkpoints": {
                "main": "HauhauCS/Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M",
                "draft": "HauhauCS/Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced-MTP:mtp-gemma-4-26B-A4B-it.gguf",
            },
            "label": ["tool-calling", "mtp"],
        }
    )
    cmd = models.pull_command(entry)
    assert cmd is not None
    assert cmd[6] == "user.Gemma4-26B-A4B-QAT-Uncensored-Balanced-Q4_K_M"
    assert cmd.count("--checkpoint") == 2
    assert cmd[cmd.index("--recipe") + 1] == "llamacpp"
    assert cmd.count("--label") == 2


def test_recipe_pin_command_for_custom_model() -> None:
    entry = models.ModelEntry.from_dict(
        {
            "alias": "coder-122b",
            "backend": "lemonade",
            "model_id": "Q122",
            "checkpoints": {"main": "SC117/x:y.gguf"},
            "recipe_options": {"ctx_size": 131072, "llamacpp_backend": "vulkan",
                               "llamacpp_args": "-np 1 -kvu --no-warmup"},
        }
    )
    cmd = models.recipe_pin_command(entry)
    assert cmd is not None
    assert cmd[:3] == ["sudo", "python3", "-c"]
    assert cmd[4] == "user.Q122"
    assert "--no-warmup" in cmd[5]
    assert cmd[6] == models.RECIPE_OPTIONS_PATH


def test_recipe_pin_command_none_without_options_or_checkpoints() -> None:
    plain = models.ModelEntry(alias="a", backend="lemonade", model_id="m")
    assert models.recipe_pin_command(plain) is None
    no_ckpt = models.ModelEntry(alias="a", backend="lemonade", model_id="m",
                                recipe_options={"ctx_size": 1})
    assert models.recipe_pin_command(no_ckpt) is None


def test_recipe_pin_snippet_merges_json(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    p = tmp_path / "recipe_options.json"
    p.write_text(json.dumps({"user.OLD": {"ctx_size": 1}}))
    subprocess.run(
        [sys.executable, "-c", models._RECIPE_PIN_SNIPPET,
         "user.Q122", json.dumps({"ctx_size": 131072}), str(p)],
        check=True,
    )
    d = json.loads(p.read_text())
    assert d["user.OLD"] == {"ctx_size": 1}
    assert d["user.Q122"] == {"ctx_size": 131072}


def test_sync_pull_pins_recipe_and_requires_pin_success(tmp_path: Path) -> None:
    root = tmp_path / "models"
    entry = models.ModelEntry.from_dict(
        {
            "alias": "coder-122b",
            "backend": "lemonade",
            "model_id": "Q122",
            "size_gb": 59.2,
            "checkpoints": {"main": "SC117/x:y.gguf"},
            "recipe_options": {"ctx_size": 131072},
        }
    )
    calls = []

    def ok_runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    results = models.sync_pull([entry], root, runner=ok_runner)
    assert results == [(entry, True)]
    assert len(calls) == 2 and calls[1][4] == "user.Q122"  # pull, then pin
    assert models.on_disk_status(entry, root) == "present"

    # pin failure -> entry FAILED, no marker, retried next sync
    root2 = tmp_path / "models2"

    def pin_fails(cmd, **kwargs):
        return _FakeCompletedProcess(1 if cmd[0] == "sudo" and cmd[1] == "python3" else 0)

    results = models.sync_pull([entry], root2, runner=pin_fails)
    assert results == [(entry, False)]
    assert models.on_disk_status(entry, root2) == "missing"


def test_from_dict_label_string_normalizes_to_list() -> None:
    entry = models.ModelEntry.from_dict(
        {"alias": "a", "backend": "lemonade", "model_id": "m", "label": "tool-calling"}
    )
    assert entry.labels == ["tool-calling"]


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

    assert calls == [["sudo", "podman", "exec", "ollama", "ollama", "pull", "llama3.3:70b"]]
    assert results == [(entries[0], True)]
    assert models.on_disk_status(entries[0], root) == "present"
    assert entries[0].marker_path(root).read_text().strip() == "llama3.3:70b"


def test_sync_pull_repulls_stale_and_refreshes_marker(tmp_path: Path) -> None:
    root = tmp_path / "models"
    old = models.ModelEntry(alias="ornith-35b", backend="lemonade", model_id="old-id", size_gb=20)
    _mark_synced(old, root)
    new = models.ModelEntry(alias="ornith-35b", backend="lemonade", model_id="new-id", size_gb=26)

    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(0)

    results = models.sync_pull([new], root, runner=fake_runner)
    assert results == [(new, True)]
    assert models.on_disk_status(new, root) == "present"


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
    _mark_synced(entry, root)

    def runner_should_not_be_called(cmd, **kwargs):
        raise AssertionError("runner must not be called for already-present entries")

    results = models.sync_pull([entry], root, runner=runner_should_not_be_called)
    assert results == []
