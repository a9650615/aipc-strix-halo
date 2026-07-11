from __future__ import annotations

from pathlib import Path


def test_spa_keeps_existing_control_endpoints() -> None:
    page = (
        Path(__file__).parents[2]
        / "modules/system-aipc-portal/web/src/pages/index.astro"
    ).read_text(encoding="utf-8")

    assert "/services/${s.id}/start" in page
    assert "/ops/baseline/start" in page
    assert "/automation/${job.task_id}/cancel" in page
    assert "/api/v1/device/events" in page
