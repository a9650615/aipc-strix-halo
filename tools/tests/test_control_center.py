from __future__ import annotations

import sys
from pathlib import Path


PORTAL_LIB = Path(__file__).parents[2] / "modules/system-aipc-portal/files/usr/lib/aipc-portal"
sys.path.insert(0, str(PORTAL_LIB))

from aipc_portal.dashboard import device_snapshot, io_snapshot, npu_snapshot, snapshot  # noqa: E402
from aipc_portal.ops import service_can_start, service_display_state, service_group  # noqa: E402
from aipc_portal.registry import ServiceMetadata, ServiceStatus  # noqa: E402


def test_device_snapshot_marks_missing_source_unavailable(tmp_path: Path) -> None:
    data = device_snapshot(tmp_path / "missing.json")

    assert data["availability"] in ("unavailable", "partial")
    assert "button" in str(data.get("detail") or data.get("summary") or "").lower() or data.get("source") == "io-only"


def test_device_snapshot_returns_published_button_state(tmp_path: Path) -> None:
    path = tmp_path / "command-center.json"
    path.write_text('{"availability":"available","button":{"state":"pressed"},"summary":"ready"}')

    data = device_snapshot(path)
    assert data["button"] == {"state": "pressed"}
    assert data["button_state"] == "pressed"
    assert data["source"] == "command-center"


def test_device_snapshot_io_only_has_human_summary(tmp_path: Path, monkeypatch) -> None:
    import aipc_portal.dashboard as dash

    monkeypatch.setattr(
        dash,
        "io_snapshot",
        lambda root=None: {
            "availability": "available",
            "ports": [
                {"id": "port0", "state": "idle", "partner": False},
                {"id": "port1", "state": "idle", "partner": False},
            ],
        },
    )
    data = device_snapshot(tmp_path / "missing.json")
    assert data["availability"] == "partial"
    assert data["ports_connected"] == 0
    assert "0/2" in data["summary"]
    assert "button offline" in data["summary"]
    # Never double-append cable phrase.
    assert data["summary"].count("0/2") == 1


def test_npu_snapshot_only_reports_explicit_npu_models(tmp_path: Path) -> None:
    device = tmp_path / "accel0"
    device.touch()

    result = npu_snapshot([{"model_name": "gemma-FLM"}, {"model_name": "vulkan-model"}], device)

    assert result["models"] == ["gemma-FLM"]


def test_io_snapshot_role_alone_is_not_connected(tmp_path: Path) -> None:
    """data_role=host [device] is dual-role idle — not a plugged cable."""
    port = tmp_path / "port0"
    port.mkdir()
    (port / "data_role").write_text("host [device]\n")
    (port / "power_role").write_text("source [sink]\n")

    ports = io_snapshot(tmp_path)["ports"]
    assert ports[0]["id"] == "port0"
    assert ports[0]["state"] == "idle"
    assert ports[0]["partner"] is False
    assert ports[0]["data_role"] == "host"


def test_io_snapshot_partner_node_means_connected(tmp_path: Path) -> None:
    port = tmp_path / "port0"
    port.mkdir()
    (port / "data_role").write_text("host [device]\n")
    (tmp_path / "port0-partner").mkdir()

    ports = io_snapshot(tmp_path)["ports"]
    assert ports[0]["state"] == "connected"
    assert ports[0]["partner"] is True


def test_usb_type_a_detects_hotplug_on_multiport_hub(tmp_path: Path) -> None:
    """Type-A: hotplug on multi-port hub; Type-C companions (maxchild=1) skipped."""
    import aipc_portal.dashboard as dash

    devices = tmp_path / "devices"
    # Multi-port hub usb3 (Type-A host) with one linked hotplug port
    hub = devices / "pci0" / "usb3"
    hub.mkdir(parents=True)
    (hub / "maxchild").write_text("5\n")
    port = hub / "3-0:1.0" / "usb3-port2"
    port.mkdir(parents=True)
    (port / "connect_type").write_text("hotplug\n")
    (port / "location").write_text("0xA\n")
    (port / "state").write_text("configured\n")
    dev = port / "device"
    dev.mkdir()
    (dev / "product").write_text("USB Receiver\n")
    # Single-port hub pair (Type-C USB companion) — must NOT appear as Type-A
    hub_c = devices / "pci1" / "usb5"
    hub_c.mkdir(parents=True)
    (hub_c / "maxchild").write_text("1\n")
    port_c = hub_c / "5-0:1.0" / "usb5-port1"
    port_c.mkdir(parents=True)
    (port_c / "connect_type").write_text("hotplug\n")
    (port_c / "location").write_text("0xC\n")

    snap = dash.usb_type_a_snapshot(tmp_path)
    assert snap["ports_total"] == 1
    assert snap["ports_connected"] == 1
    assert snap["ports"][0]["product"] == "USB Receiver"
    assert snap["ports"][0]["kind"] == "type-a"


def test_service_can_start_only_for_unhealthy_unit_backed() -> None:
    assert service_can_start("active", True) is False
    assert service_can_start("active", None) is False
    assert service_can_start("n/a", True) is False  # health-only card, no unit
    assert service_can_start("n/a", False) is False
    assert service_can_start("inactive", None) is True
    assert service_can_start("failed", False) is True
    assert service_can_start("activating", None) is False
    assert service_display_state("n/a", True) == "ready"
    assert service_display_state("inactive", None) == "inactive"
    assert service_group("lemonade") == "LLM"
    assert service_group("sensevoice") == "Voice"


def test_snapshot_migrates_service_status_without_fabricating_device_state(tmp_path: Path) -> None:
    service = ServiceMetadata(id="voice", title="Voice", module="voice", kind="voice")
    result = snapshot(
        [ServiceStatus(service, "active", True, "200 ok")],
        models=[{"model_name": "resident-small"}],
        automation=[],
        device_path=tmp_path / "missing.json",
        npu_device=tmp_path / "missing-npu",
    )

    assert result["services"] == [
        {
            "id": "voice",
            "title": "Voice",
            "state": "active",
            "ui": None,
            "health": True,
            "display_state": "active",
            "can_start": False,
            "group": "System",
        }
    ]
    assert result["models"] == [{"model_name": "resident-small"}]
    assert result["device"]["availability"] in ("unavailable", "partial")
    assert result["npu"]["availability"] == "unavailable"
    assert result["automation"] == []
    assert "model" in result["runtime"]["summary"].lower() or result["runtime"]["model_count"] == 1
    assert result["platform"]["availability"] == "available"
    assert "summary" in result["platform"]


def test_platform_snapshot_reports_mem_shape(monkeypatch) -> None:
    import aipc_portal.dashboard as dash

    monkeypatch.setattr(dash, "_meminfo", lambda: {"mem_total_gb": 128.0, "mem_available_gb": 90.0})
    monkeypatch.setattr(dash, "_gtt_info", lambda: {"gtt_used_gb": 1.2, "gtt_total_gb": 122.0})
    monkeypatch.setattr(dash, "_cpu_label", lambda: "Ryzen AI MAX+ 395")
    monkeypatch.setattr(dash, "_hostname", lambda: "aipc")
    monkeypatch.setattr(dash, "_kernel_release", lambda: "6.14.0")
    monkeypatch.setattr(dash, "_os_release", lambda: {"NAME": "Bazzite", "VERSION": "44"})
    monkeypatch.setattr(
        dash,
        "_read_text",
        lambda path: "performance" if "choices" not in str(path) else "quiet balanced performance",
    )
    data = dash.platform_snapshot()
    assert data["cpu"] == "Ryzen AI MAX+ 395"
    assert "90" in data["summary"]
    assert data["profile"] == "performance"
    assert data["hostname"] == "aipc"
    assert data["chassis"]
    assert "balanced" in data["profile_choices"]


def test_runtime_snapshot_lists_models() -> None:
    import aipc_portal.dashboard as dash

    data = dash.runtime_snapshot(
        [{"model_name": "gemma4-it-e4b-FLM", "backend": "lemonade", "device": "npu", "pinned": True}],
        services=[{"id": "sensevoice", "state": "active", "health": True}],
    )
    assert data["model_count"] == 1
    assert data["models"][0]["name"] == "gemma4-it-e4b-FLM"
    # Status stays short — long HF names are only in models[].
    assert "gemma4" not in data["summary"]
    assert "1 model" in data["summary"]


def test_snapshot_cache_avoids_repeated_live_probes(monkeypatch) -> None:
    import aipc_portal.dashboard as dash

    calls = {"n": 0}

    def fake_build(*_a, **_k):
        calls["n"] += 1
        return {"summary": f"build-{calls['n']}"}

    monkeypatch.setattr(dash, "_build_snapshot", fake_build)
    with dash._snapshot_lock:
        dash._snapshot_cache = None
        dash._snapshot_cache_at = 0.0
    first = dash.snapshot()
    second = dash.snapshot()
    assert first == second == {"summary": "build-1"}
    assert calls["n"] == 1


def test_loaded_models_uses_short_timeout(monkeypatch) -> None:
    import aipc_portal.dashboard as dash

    seen: list[float] = []

    def fake_http(url: str, timeout: float = 0.4):
        seen.append(timeout)
        if "11434" in url:
            return {"models": [{"name": "x"}]}
        return {}

    monkeypatch.setattr(dash, "_http_json", fake_http)
    rows = dash.loaded_models()
    assert rows == [{"name": "x", "backend": "ollama"}]
    assert seen and all(t <= 0.5 for t in seen)
