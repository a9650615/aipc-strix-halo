from __future__ import annotations

from aipc_lib.model_presets import PRESETS, plan_switch
from aipc_lib.models import ModelEntry


def _entries() -> list[ModelEntry]:
    return [
        ModelEntry("resident-small", "lemonade", "gemma4-it-e4b-FLM", 9.6),
        ModelEntry("coder-agentic", "lemonade", "Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P", 21.8),
        ModelEntry(
            "assistant-gemma",
            "lemonade",
            "Gemma4-26B-A4B-QAT-Uncensored-Balanced-Q4_K_M",
            15.6,
        ),
        ModelEntry("ornith-35b", "lemonade", "Ornith-1.0-35B-GGUF-Q4_K_M", 19.7),
        ModelEntry("qwythos-9b", "lemonade", "Qwythos-9B-Claude-Mythos-5-1M-Q4_K_M", 5.6),
        ModelEntry("qwen35-122b-q3", "ollama", "qwen3.5:122b-aipc", 81.4),
        ModelEntry("main-cloud", "anthropic", "claude-sonnet-4-6", "cloud"),
    ]


def test_presets_documented() -> None:
    assert set(PRESETS) == {"agent", "122b", "free"}


def test_agent_unloads_only_giant_when_loaded() -> None:
    plan = plan_switch(
        "agent",
        _entries(),
        loaded_ollama_ids={"qwen3.5:122b-aipc"},
        loaded_lemonade_ids={"Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P"},
    )
    assert [u.alias for u in plan.unloads] == ["qwen35-122b-q3"]
    assert plan.warm is not None
    assert plan.warm.alias == "qwythos-9b"


def test_122b_unloads_lemonade_vulkan_keeps_resident() -> None:
    plan = plan_switch(
        "122b",
        _entries(),
        loaded_ollama_ids=set(),
        loaded_lemonade_ids={
            "gemma4-it-e4b-FLM",
            "Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P",
            "Ornith-1.0-35B-GGUF-Q4_K_M",
            "Qwythos-9B-Claude-Mythos-5-1M-Q4_K_M",
        },
    )
    aliases = {u.alias for u in plan.unloads}
    assert "resident-small" not in aliases
    assert "coder-agentic" in aliases
    assert "ornith-35b" in aliases
    assert "qwythos-9b" in aliases
    assert plan.warm is not None
    assert plan.warm.alias == "qwen35-122b-q3"
    assert plan.warm.model_id == "qwen3.5:122b-aipc"


def test_free_unloads_heavy_both_backends() -> None:
    plan = plan_switch(
        "free",
        _entries(),
        loaded_ollama_ids={"qwen3.5:122b-aipc"},
        loaded_lemonade_ids={
            "gemma4-it-e4b-FLM",
            "Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P",
        },
    )
    aliases = {u.alias for u in plan.unloads}
    assert aliases == {"qwen35-122b-q3", "coder-agentic"}
    assert plan.warm is None


def test_none_loaded_sets_plan_all_candidates() -> None:
    plan = plan_switch("122b", _entries(), loaded_ollama_ids=None, loaded_lemonade_ids=None)
    aliases = {u.alias for u in plan.unloads}
    assert "resident-small" not in aliases
    assert "coder-agentic" in aliases
    assert "assistant-gemma" in aliases
    assert "qwythos-9b" in aliases


def test_unknown_preset_raises() -> None:
    try:
        plan_switch("nope", _entries())
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unknown preset" in str(e)


def test_cli_models_use_list(monkeypatch, tmp_path) -> None:
    from click.testing import CliRunner
    from aipc_lib import cli

    manifest = tmp_path / "models.yaml"
    manifest.write_text(
        "models:\n"
        "  - {alias: qwen35-122b-q3, backend: ollama, model_id: qwen3.5:122b-aipc}\n"
    )
    result = CliRunner().invoke(cli.main, ["models", "use", "--list"])
    assert result.exit_code == 0, result.output
    assert "agent:" in result.output
    assert "122b:" in result.output


def test_cli_models_use_dry_run(monkeypatch, tmp_path) -> None:
    from click.testing import CliRunner
    from aipc_lib import cli

    manifest = tmp_path / "models.yaml"
    manifest.write_text(
        "models:\n"
        "  - {alias: qwen35-122b-q3, backend: ollama, model_id: qwen3.5:122b-aipc}\n"
        "  - {alias: coder-agentic, backend: lemonade, model_id: Qwen3.6-35B}\n"
        "  - {alias: resident-small, backend: lemonade, model_id: gemma4-it-e4b-FLM}\n"
    )
    result = CliRunner().invoke(
        cli.main,
        ["models", "use", "122b", "--dry-run", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.output
    assert "preset: 122b" in result.output
    assert "coder-agentic" in result.output
    assert "resident-small" not in result.output or "unload: resident-small" not in result.output
    assert "warm: qwen35-122b-q3" in result.output
