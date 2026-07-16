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
    assert "/api/v1/dashboard" in page
    assert "createJsonPoller" in page
    assert "renderPlatform" in page
    assert "renderRuntime" in page
    assert "renderOps" in page
    assert "ops-services" in page
    assert "serviceCanStart" in page
    assert "platform-metrics" in page
    assert "p:last-child" not in page
    # Must use CSS id selectors with # — bare $("ops-svc-count") throws and empties the panel.
    assert '$("#ops-svc-count")' in page or "ops-svc-count" in page
    assert '$("ops-svc-count")' not in page
    assert '$("ops-auto-count")' not in page


def test_memory_page_uses_portal_memory_api_and_nav_link_exists() -> None:
    root = Path(__file__).parents[2] / "modules/system-aipc-portal/web/src"
    page = (root / "pages/memory.astro").read_text(encoding="utf-8")

    assert "/api/v1/memories?" in page
    assert "/api/v1/memories/search" in page
    assert "/api/v1/memories/${m.id}" in page
    assert 'method: "DELETE"' in page
    assert "confirm(" in page

    layout = (root / "layouts/App.astro").read_text(encoding="utf-8")
    assert 'href="/memory"' in layout and "data-astro-reload" in layout
    assert 'data-i18n="nav.memory"' in layout
    assert 'href="/#device"' not in layout
    assert 'href="/#ai"' not in layout
    assert 'href="/#services"' not in layout


def test_agents_page_uses_portal_agents_api_and_nav_link_exists() -> None:
    root = Path(__file__).parents[2] / "modules/system-aipc-portal/web/src"
    page = (root / "pages/agents.astro").read_text(encoding="utf-8")

    assert "/api/v1/agents" in page
    assert "createJsonPoller" in page
    assert "/api/v1/agents/delegations/" in page
    assert "/api/v1/agents/kanban/" in page
    assert "/api/v1/agents/logs?" in page
    assert "agent-workspace" in page
    assert "agent-row" in page or "work-list" in page
    assert "agents.tab.all" in page or "全部" in page

    layout = (root / "layouts/App.astro").read_text(encoding="utf-8")
    assert 'href="/agents"' in layout and "data-astro-reload" in layout


def test_nav_only_lists_real_pages() -> None:
    layout = (
        Path(__file__).parents[2]
        / "modules/system-aipc-portal/web/src/layouts/App.astro"
    ).read_text(encoding="utf-8")
    # Same-page hash "tabs" looked like separate views but were not.
    assert 'href="/#device"' not in layout
    assert "AI &amp; Voice" not in layout
    assert 'href="/" data-astro-reload' in layout
    assert 'href="/models" data-astro-reload' in layout
    assert 'href="/agents" data-astro-reload' in layout
    assert 'href="/memory" data-astro-reload' in layout


def test_models_page_uses_scheduling_api() -> None:
    root = Path(__file__).parents[2] / "modules/system-aipc-portal/web/src"
    page = (root / "pages/models.astro").read_text(encoding="utf-8")
    assert "/api/v1/models" in page
    assert "createJsonPoller" in page
    assert "models.policy" in page or "SMO" in page
    assert "models.journal" in page or "閒置" in page
    assert "OOM" in page
    poll = (root / "scripts/poll.js").read_text(encoding="utf-8")
    assert "If-None-Match" in poll
    assert "visibilityState" in poll


def test_ui_has_chinese_i18n_and_lang_toggle() -> None:
    root = Path(__file__).parents[2] / "modules/system-aipc-portal/web/src"
    layout = (root / "layouts/App.astro").read_text(encoding="utf-8")
    i18n = (root / "scripts/i18n.js").read_text(encoding="utf-8")
    home = (root / "pages/index.astro").read_text(encoding="utf-8")
    assert 'data-set-lang="zh"' in layout
    assert 'data-i18n="nav.home"' in layout
    assert "控制中心" in i18n or '"brand.sub": "控制中心"' in i18n
    assert 'data-i18n="home.title"' in home
    assert 'from "../scripts/i18n.js"' in home
