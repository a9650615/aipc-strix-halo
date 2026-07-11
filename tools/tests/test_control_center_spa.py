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
    assert "#${id} .status" in page
    assert "p:last-child" not in page


def test_memory_page_uses_portal_memory_api_and_nav_link_exists() -> None:
    root = Path(__file__).parents[2] / "modules/system-aipc-portal/web/src"
    page = (root / "pages/memory.astro").read_text(encoding="utf-8")

    assert "/api/v1/memories?" in page
    assert "/api/v1/memories/search" in page
    assert "/api/v1/memories/${m.id}" in page
    assert 'method: "DELETE"' in page
    assert "confirm(" in page

    layout = (root / "layouts/App.astro").read_text(encoding="utf-8")
    assert '<a href="/memory" data-astro-reload>' in layout
