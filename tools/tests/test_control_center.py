from __future__ import annotations

import sys
from pathlib import Path


PORTAL_LIB = Path(__file__).parents[2] / "modules/system-aipc-portal/files/usr/lib/aipc-portal"
sys.path.insert(0, str(PORTAL_LIB))

from aipc_portal.dashboard import device_snapshot, io_snapshot, npu_snapshot, snapshot  # noqa: E402
from aipc_portal.registry import ServiceMetadata, ServiceStatus  # noqa: E402


def test_device_snapshot_marks_missing_source_unavailable(tmp_path: Path) -> None:
    data = device_snapshot(tmp_path / "missing.json")

    assert data["availability"] == "unavailable"
    assert "not found" in data["detail"]


def test_device_snapshot_returns_published_button_state(tmp_path: Path) -> None:
    path = tmp_path / "command-center.json"
    path.write_text('{"availability":"available","button":{"state":"pressed"}}')

    assert device_snapshot(path)["button"] == {"state": "pressed"}


def test_npu_snapshot_only_reports_explicit_npu_models(tmp_path: Path) -> None:
    device = tmp_path / "accel0"
    device.touch()

    result = npu_snapshot([{"model_name": "gemma-FLM"}, {"model_name": "vulkan-model"}], device)

    assert result["models"] == ["gemma-FLM"]


def test_io_snapshot_reports_type_c_port_state(tmp_path: Path) -> None:
    port = tmp_path / "port0"
    port.mkdir()
    (port / "data_role").write_text("host\n")

    assert io_snapshot(tmp_path)["ports"] == [{"id": "port0", "state": "connected"}]


def test_snapshot_migrates_service_status_without_fabricating_device_state(tmp_path: Path) -> None:
    service = ServiceMetadata(id="voice", title="Voice", module="voice", kind="voice")
    result = snapshot(
        [ServiceStatus(service, "active", True, "200 ok")],
        models=[{"model_name": "resident-small"}],
        automation=[],
        device_path=tmp_path / "missing.json",
        npu_device=tmp_path / "missing-npu",
    )

    assert result["services"] == [{"id": "voice", "title": "Voice", "state": "active"}]
    assert result["models"] == [{"model_name": "resident-small"}]
    assert result["device"]["availability"] == "unavailable"
    assert result["npu"]["availability"] == "unavailable"
    assert result["automation"] == []
