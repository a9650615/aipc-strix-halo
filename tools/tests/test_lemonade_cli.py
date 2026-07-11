from __future__ import annotations

import urllib.error
from pathlib import Path

from click.testing import CliRunner

from aipc_lib import cli
from aipc_lib.models import ModelEntry


def test_lemonade_unload_resolves_alias_and_posts_model_id(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        cli.models_mod,
        "load_manifest",
        lambda path: [
            ModelEntry(
                alias="coder-agentic",
                backend="lemonade",
                model_id="Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P",
            )
        ],
    )
    monkeypatch.setattr(cli.models_mod, "DEFAULT_MANIFEST", Path("/tmp/models.yaml"))
    monkeypatch.setattr(
        cli,
        "_lemonade_post",
        lambda base_url, path, payload: calls.append((base_url, path, payload)),
    )

    result = CliRunner().invoke(cli.main, ["lemonade", "unload", "coder-agentic"])

    assert result.exit_code == 0
    assert calls == [
        (
            "http://127.0.0.1:8001",
            "/api/v0/unload",
            {"model_name": "Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P"},
        )
    ]
    assert "coder-agentic -> Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P" in result.output


def test_lemonade_unload_accepts_raw_model_id(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(cli.models_mod, "load_manifest", lambda path: [])
    monkeypatch.setattr(cli, "_lemonade_post", lambda base_url, path, payload: calls.append(payload))

    result = CliRunner().invoke(cli.main, ["lemonade", "unload", "raw-model-id"])

    assert result.exit_code == 0
    assert calls == [{"model_name": "raw-model-id"}]


def test_lemonade_unload_reports_restart_hint_on_failure(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cli.models_mod, "load_manifest", lambda path: [])
    monkeypatch.setattr(cli, "_lemonade_post", fail)

    result = CliRunner().invoke(cli.main, ["lemonade", "unload", "coder-agentic"])

    assert result.exit_code == 1
    assert "lemonade unload failed" in result.output
    assert "sudo systemctl restart lemonade.service" in result.output


def test_lemonade_unload_reports_restart_hint_on_timeout(monkeypatch) -> None:
    monkeypatch.setattr(cli.models_mod, "load_manifest", lambda path: [])
    monkeypatch.setattr(
        cli,
        "_lemonade_post",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    result = CliRunner().invoke(cli.main, ["lemonade", "unload", "ornith-35b"])

    assert result.exit_code == 1
    assert "lemonade unload failed" in result.output
    assert "timed out" in result.output
    assert "sudo systemctl restart lemonade.service" in result.output
