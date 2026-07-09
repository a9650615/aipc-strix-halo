from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from aipc_lib import portal
from aipc_lib.portal import CardProbe, ServiceMetadata


def test_matches_open_portal_intent_zh_en() -> None:
    assert portal.matches_open_portal_intent("打开 dashboard")
    assert portal.matches_open_portal_intent("打開管理介面")
    assert portal.matches_open_portal_intent("open portal")
    assert portal.matches_open_portal_intent("Open the dashboard please")
    assert portal.matches_open_portal_intent("dashboard")
    # Real SenseVoice slip from hardware: double "ash"
    assert portal.matches_open_portal_intent("打开 dashashboard。")
    assert portal.matches_open_portal_intent("打开dashbord")
    assert not portal.matches_open_portal_intent("今天天气怎么样")
    assert not portal.matches_open_portal_intent("remember my birthday")


def test_ensure_and_open_portal_starts_then_opens(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(portal, "ensure_portal_running", lambda url=None: True)
    monkeypatch.setattr(
        portal,
        "open_portal",
        lambda url: calls.append(url),
    )
    ok, msg = portal.ensure_and_open_portal("http://127.0.0.1:7080")
    assert ok
    assert "7080" in msg
    assert calls == ["http://127.0.0.1:7080"]


def test_load_service_metadata_accepts_mem0_yaml(tmp_path: Path) -> None:
    services = tmp_path / "services"
    services.mkdir()
    (services / "mem0.yaml").write_text(
        """
id: mem0
title: Mem0 Memory
module: memory-mem0
kind: memory
systemd: aipc-mem0.service
health: http://127.0.0.1:7000/healthz
endpoint: http://127.0.0.1:7000
tags:
  - memory
  - baseline
""".strip()
        + "\n",
        encoding="utf-8",
    )

    loaded = portal.load_service_metadata(services)

    assert len(loaded) == 1
    assert loaded[0].id == "mem0"
    assert loaded[0].title == "Mem0 Memory"
    assert loaded[0].health == "http://127.0.0.1:7000/healthz"
    assert loaded[0].tags == ("memory", "baseline")


def test_empty_registry_still_renders() -> None:
    html = portal.render_portal_html([])
    assert "AIPC Portal" in html
    assert "No AIPC services declared yet" in html
    assert 'http-equiv="refresh"' in html


def test_render_portal_html_links_to_declared_ui() -> None:
    service = portal.ServiceMetadata(
        id="mem0",
        title="Mem0 Memory",
        module="memory-mem0",
        kind="memory",
        ui="http://127.0.0.1:3000/",
        tags=("memory", "dashboard"),
    )

    html = portal.render_portal_html([service])

    assert "Mem0 Memory" in html
    assert "http://127.0.0.1:3000/" in html
    assert "Open" in html


def test_invalid_metadata_skipped(tmp_path: Path) -> None:
    services = tmp_path / "services"
    services.mkdir()
    (services / "bad.yaml").write_text("title: only\n", encoding="utf-8")
    (services / "good.yaml").write_text(
        "id: ok\ntitle: Ok\nmodule: m\nkind: k\n",
        encoding="utf-8",
    )
    loaded = portal.load_service_metadata(services)
    assert [s.id for s in loaded] == ["ok"]


def test_portal_url_reads_endpoint_file(tmp_path: Path) -> None:
    endpoint = tmp_path / "endpoint"
    endpoint.write_text("http://127.0.0.1:7080\n", encoding="utf-8")

    assert portal.portal_url(endpoint) == "http://127.0.0.1:7080"


def test_open_portal_uses_xdg_open() -> None:
    calls: list[list[str]] = []

    def runner(args: list[str], check: bool = False) -> object:
        calls.append(args)
        return object()

    portal.open_portal("http://127.0.0.1:7080", runner=runner)

    assert calls == [["xdg-open", "http://127.0.0.1:7080"]]


def test_format_status_lines() -> None:
    meta = ServiceMetadata(
        id="mem0",
        title="Mem0",
        module="memory-mem0",
        kind="memory",
        systemd="aipc-mem0.service",
        health="http://127.0.0.1:7000/healthz",
    )
    text = portal.format_status_lines(
        [CardProbe(meta, "active", True, "200 ok")],
        url="http://127.0.0.1:7080",
        server_state="running",
    )
    assert "http://127.0.0.1:7080" in text
    assert "mem0" in text
    assert "ok" in text


def test_probe_cards_injection() -> None:
    meta = ServiceMetadata(
        id="x",
        title="X",
        module="m",
        kind="k",
        systemd="u.service",
        health="http://127.0.0.1:1/h",
    )
    probes = portal.probe_cards(
        [meta],
        unit_active=lambda name: "active",
        probe_http=lambda url, timeout=2.0: (True, "200"),
    )
    assert len(probes) == 1
    assert probes[0].ok is True


def test_portal_cli_help() -> None:
    from aipc_lib import cli

    result = CliRunner().invoke(cli.main, ["portal", "--help"])
    assert result.exit_code == 0
    assert "open" in result.output
    assert "serve" in result.output


def test_portal_cli_status_dry(monkeypatch) -> None:
    from aipc_lib import cli

    monkeypatch.setattr(cli.portal_mod, "portal_url", lambda: "http://127.0.0.1:7080")
    monkeypatch.setattr(cli.portal_mod, "portal_status", lambda url: "unreachable")
    monkeypatch.setattr(
        cli.portal_mod,
        "collect_status",
        lambda **kwargs: [
            CardProbe(
                ServiceMetadata(
                    id="portal",
                    title="Portal",
                    module="system-aipc-portal",
                    kind="system",
                ),
                "n/a",
                None,
                "not declared",
            )
        ],
    )
    result = CliRunner().invoke(cli.main, ["portal"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:7080" in result.output
    assert "portal" in result.output


def test_shipped_module_metadata_parses() -> None:
    roots = portal.repo_services_dirs()
    assert roots, "expected at least one modules/*/files/etc/aipc/portal/services"
    loaded = portal.load_service_metadata(roots=roots)
    ids = {s.id for s in loaded}
    assert "aipc-portal" in ids
    assert "mem0" in ids
    assert "sensevoice" in ids
    assert "kokoro" in ids
