from __future__ import annotations

import json
import urllib.error
from pathlib import Path

from click.testing import CliRunner

from aipc_lib import cli
from aipc_lib import status_dashboard
from aipc_lib.models import ModelEntry


def _make_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    manifest = tmp_path / "models.yaml"
    manifest.write_text(
        "models:\n" + "\n".join("  - " + json.dumps(e) for e in entries)
    )
    return manifest


def test_loaded_lemonade_returns_loaded_models() -> None:
    responses = [
        json.dumps({
            "all_models_loaded": [
                {"model_name": "m1", "loaded": True, "pinned": False},
                {"model_name": "m2", "loaded": False, "pinned": False},
                {"model_name": "m3", "loaded": True, "pinned": True},
            ]
        }).encode(),
    ]
    call_idx = 0

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            nonlocal call_idx
            r = responses[call_idx]
            call_idx += 1
            return r

    fake_resp = FakeResp()
    monkeypatch_urlopen = lambda url, timeout=None: fake_resp

    orig = status_dashboard.urllib.request.urlopen
    status_dashboard.urllib.request.urlopen = monkeypatch_urlopen
    try:
        result = status_dashboard.loaded_lemonade_models(base_url="http://x")
    finally:
        status_dashboard.urllib.request.urlopen = orig

    assert result is not None
    assert len(result) == 2
    assert result[0]["model_name"] == "m1"
    assert result[1]["model_name"] == "m3"


def test_loaded_lemonade_returns_none_when_unreachable() -> None:
    orig = status_dashboard.urllib.request.urlopen
    status_dashboard.urllib.request.urlopen = lambda url, timeout=None: (_ for _ in ()).throw(
        urllib.error.URLError("refused")
    )
    try:
        assert status_dashboard.loaded_lemonade_models(base_url="http://x") is None
    finally:
        status_dashboard.urllib.request.urlopen = orig


def test_models_loaded_ollama_shows_loaded_models(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "coder-agentic", "backend": "ollama", "model_id": "gemma4:26b"}],
    )
    monkeypatch.setattr(
        cli.status_mod, "loaded_models",
        lambda base_url=None: [
            {"name": "gemma4:26b", "size": 15e9, "expires_at": 999},
        ],
    )

    result = CliRunner().invoke(
        cli.main, ["models", "loaded", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.output
    assert "coder-agentic" in result.output
    assert "gemma4:26b" in result.output
    assert "15.0GB" in result.output


def test_models_loaded_lemonade_shows_loaded_models(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [
            {
                "alias": "ornith-35b",
                "backend": "lemonade",
                "model_id": "user.Ornith-35B-A11B-GGUF-Q3_K_S",
            },
            {
                "alias": "resident-small",
                "backend": "lemonade",
                "model_id": "resident-small-alias",
            },
        ],
    )
    monkeypatch.setattr(
        cli.status_mod, "loaded_lemonade_models",
        lambda base_url=None: [
            {
                "model_name": "user.Ornith-35B-A11B-GGUF-Q3_K_S",
                "loaded": True,
                "pinned": False,
                "vram_loaded": True,
            },
        ],
    )

    result = CliRunner().invoke(
        cli.main, ["models", "loaded", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.output
    assert "ornith-35b" in result.output
    assert "resident-small" not in result.output
    assert "vram_loaded" in result.output


def test_models_loaded_reports_unreachable_backend(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "coder-agentic", "backend": "ollama", "model_id": "x"}],
    )
    monkeypatch.setattr(
        cli.status_mod, "loaded_models", lambda base_url=None: None,
    )

    result = CliRunner().invoke(
        cli.main, ["models", "loaded", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.output
    assert "not reachable" in result.output


def test_models_loaded_no_local_models_declared(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "gpt4o", "backend": "openai", "model_id": "gpt-4o"}],
    )

    result = CliRunner().invoke(
        cli.main, ["models", "loaded", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.output
    assert "No local-backend models" in result.output


def test_models_unload_ollama_posts_keep_alive_zero(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "coder-agentic", "backend": "ollama", "model_id": "gemma4:26b"}],
    )

    captured = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return b""

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else None
        data = req.data if hasattr(req, "data") else None
        method = req.method if hasattr(req, "method") else None
        captured.append({"url": url, "data": data, "method": method})
        return FakeResp()

    monkeypatch.setattr(
        cli.urllib.request, "urlopen", fake_urlopen,
    )

    result = CliRunner().invoke(
        cli.main, ["models", "unload", "coder-agentic", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert "api/generate" in captured[0]["url"]
    payload = json.loads(captured[0]["data"])
    assert payload == {"model": "gemma4:26b", "keep_alive": 0}
    assert "gemma4:26b" in result.output


def test_models_unload_lemonade_posts_model_id(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "ornith-35b", "backend": "lemonade", "model_id": "user.Ornith-35B"}],
    )

    captured = []
    monkeypatch.setattr(
        cli.models_mod, "load_manifest",
        lambda path: [
            ModelEntry(
                alias="ornith-35b",
                backend="lemonade",
                model_id="user.Ornith-35B",
            )
        ],
    )
    monkeypatch.setattr(
        cli, "_lemonade_post",
        lambda base_url, path, payload: captured.append((base_url, path, payload)),
    )

    result = CliRunner().invoke(
        cli.main, ["models", "unload", "ornith-35b", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.output
    assert captured == [
        (
            "http://127.0.0.1:8001",
            "/api/v0/unload",
            {"model_name": "user.Ornith-35B"},
        )
    ]
    assert "user.Ornith-35B" in result.output


def test_models_unload_lemonade_timeout_exits_1_with_restart_hint(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "ornith-35b", "backend": "lemonade", "model_id": "user.Ornith-35B"}],
    )
    monkeypatch.setattr(
        cli,
        "_lemonade_post",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    result = CliRunner().invoke(
        cli.main, ["models", "unload", "ornith-35b", "--manifest", str(manifest)],
    )

    assert result.exit_code == 1
    assert "lemonade unload failed for user.Ornith-35B" in result.output
    assert "timed out" in result.output
    assert "sudo systemctl restart lemonade.service" in result.output


def test_models_unload_unknown_alias_exits_1(tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "coder-agentic", "backend": "ollama", "model_id": "gemma4:26b"}],
    )

    result = CliRunner().invoke(
        cli.main, ["models", "unload", "ghost-model", "--manifest", str(manifest)],
    )
    assert result.exit_code == 1
    assert "unknown alias" in result.output


def test_models_unload_cloud_model_exits_1(tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "gpt4o", "backend": "openai", "model_id": "gpt-4o"}],
    )

    result = CliRunner().invoke(
        cli.main, ["models", "unload", "gpt4o", "--manifest", str(manifest)],
    )
    assert result.exit_code == 1
    assert "cloud model" in result.output


def test_models_unload_ollama_failure_exits_1(monkeypatch, tmp_path: Path) -> None:
    manifest = _make_manifest(
        tmp_path,
        [{"alias": "coder-agentic", "backend": "ollama", "model_id": "gemma4:26b"}],
    )

    monkeypatch.setattr(
        cli.urllib.request, "Request",
        lambda url, data=None, method=None, headers=None: None,
    )
    monkeypatch.setattr(
        cli.urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    result = CliRunner().invoke(
        cli.main, ["models", "unload", "coder-agentic", "--manifest", str(manifest)],
    )
    assert result.exit_code == 1
    assert "ollama unload failed" in result.output
