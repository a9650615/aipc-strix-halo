from __future__ import annotations

from aipc_lib import voice_ops
from aipc_lib.voice_ops import Probe


def test_format_status_marks_ok_and_fail() -> None:
    text = voice_ops.format_status(
        [
            Probe("sensevoice", "unit=active", True),
            Probe("kokoro", "down", False),
        ]
    )
    assert "sensevoice" in text and "kokoro" in text
    assert text.startswith("ok") or "\nok" in text or text.lstrip().startswith("ok")
    assert "!!" in text


def test_collect_baseline_status_order_and_injection() -> None:
    probes = voice_ops.collect_baseline_status(
        unit_active=lambda name: "active",
        cont_status=lambda name: "running",
        probe_http=lambda url, timeout=2.0: (True, "200 ok"),
        resident=lambda: Probe("resident-small", "lemonade ok", True),
    )
    names = [p.name for p in probes]
    # Closed loop order: hear → think → speak → remember → manage
    assert names[:6] == [
        "sensevoice",
        "resident-small",
        "litellm",
        "chat",
        "kokoro",
        "mem0",
    ]
    assert "portal" in names
    assert all(
        p.ok
        for p in probes
        if p.name in ("sensevoice", "kokoro", "mem0", "resident-small", "chat", "portal")
    )


def test_plan_start_includes_closed_loop() -> None:
    cmds = [" ".join(c) for c in voice_ops.plan_start()]
    assert any("aipc-mem0" in c for c in cmds)
    assert any("sensevoice" in c for c in cmds)
    assert any("orchestrator" in c for c in cmds)
    assert any("litellm" in c for c in cmds)
    assert any("aipc-kokoro" in c or "podman start" in c for c in cmds)


def test_plan_stop_leaves_mem0() -> None:
    joined = " ".join(" ".join(c) for c in voice_ops.plan_stop())
    assert "sensevoice" in joined
    assert "mem0" not in joined
    assert "resident" not in joined


def test_apply_plan_dry_run() -> None:
    results = voice_ops.apply_plan(voice_ops.plan_start(), dry_run=True)
    assert results
    assert all(code == 0 and msg == "dry-run" for _, code, msg in results)


def test_voice_cli_status(monkeypatch) -> None:
    from click.testing import CliRunner

    from aipc_lib import cli

    monkeypatch.setattr(
        cli.voice_ops_mod,
        "collect_baseline_status",
        lambda: [
            Probe("sensevoice", "ok", True),
            Probe("kokoro", "ok", True),
            Probe("mem0", "ok", True),
        ],
    )
    result = CliRunner().invoke(cli.main, ["voice", "status"])
    assert result.exit_code == 0
    assert "sensevoice" in result.output


def test_voice_cli_stop_requires_yes() -> None:
    from click.testing import CliRunner

    from aipc_lib import cli

    result = CliRunner().invoke(cli.main, ["voice", "stop"])
    assert result.exit_code == 1
    assert "--yes" in result.output
