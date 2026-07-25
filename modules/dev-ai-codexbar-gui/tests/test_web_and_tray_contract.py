"""Gating contracts for web HTML surface, tray paint, Wayland popover path."""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_primary_usage_ui_is_popover_via_shell_adapter() -> None:
    """UI stays UsagePopover; shell_adapter may host it in SNI QMenu (no rewrite)."""
    tray = (GUI_DIR / "codexbar_gui" / "tray_app.py").read_text()
    pop = (GUI_DIR / "codexbar_gui" / "popover.py").read_text()
    shell = (GUI_DIR / "codexbar_gui" / "shell_adapter.py").read_text()
    assert "from codexbar_gui.popover import UsagePopover" in tray
    assert "build_tray_shell" in tray
    assert "class UsagePopover(QWidget)" in pop
    assert "class UsagePopover(QMenu)" not in pop
    assert "SniMenuTrayShell" in shell
    assert "WindowTrayShell" in shell
    assert "QWidgetAction" in shell


def test_popover_constructs_with_web_url() -> None:
    """Regression: set_web_url must not run before Open Web button exists."""
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.popover import UsagePopover
    from codexbar_gui.upstream import parse_upstream_list

    _ = QApplication.instance() or QApplication([])
    pop = UsagePopover(web_url="http://127.0.0.1:8787/")
    assert pop._web_url == "http://127.0.0.1:8787/"
    assert pop._web_btn.isEnabled()
    views = parse_upstream_list(
        [
            {
                "provider": "codex",
                "source": "oauth",
                "version": "0.142.5",
                "credits": {"remaining": 0},
                "usage": {
                    "accountEmail": "a@b.c",
                    "loginMethod": "plus",
                    "primary": {
                        "usedPercent": 1,
                        "windowMinutes": 300,
                        "resetsAt": "2099-01-01T00:00:00Z",
                    },
                    "secondary": {
                        "usedPercent": 0,
                        "windowMinutes": 10080,
                        "resetsAt": "2099-07-01T00:00:00Z",
                    },
                },
            }
        ]
    )
    pop._views = views
    pop._costs = {}
    pop._active = "codex"
    pop._rebuild_tabs()
    pop._rebuild_body()
    assert pop._body_layout.count() >= 1


def test_paint_dual_bar_non_null() -> None:
    """Tray is dual remaining capsules (IconRenderer), not digit tile."""
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.icon_updater import paint_dual_window_pixmap, paint_usage_pixmap

    _ = QApplication.instance() or QApplication([])
    pm = paint_dual_window_pixmap(
        primary_remaining=99.0, secondary_remaining=23.0, size=24
    )
    assert not pm.isNull()
    assert pm.width() >= 24
    img = pm.toImage()
    opaque = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if img.pixelColor(x, y).alpha() > 0:
                opaque += 1
    assert opaque > 20
    # Entry point prefers dual bars
    assert not paint_usage_pixmap(
        primary_remaining=50.0, secondary_remaining=80.0, size=24
    ).isNull()


def test_paint_weekly_only_collapses_to_single_bar() -> None:
    """primary=null + weekly secondary → single capsule, not empty+weekly."""
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.icon_updater import (
        _normalize_window_rems,
        paint_dual_window_pixmap,
        paint_usage_pixmap,
    )

    _ = QApplication.instance() or QApplication([])
    top, bot, style = _normalize_window_rems(None, 41.0, "dual_bars")
    assert (top, bot, style) == (41.0, None, "primary_only")
    # Must not copy remaining into a fake session bar alongside weekly
    pm = paint_usage_pixmap(
        remaining=41.0,
        primary_remaining=None,
        secondary_remaining=41.0,
        size=24,
        icon_style="dual_bars",
    )
    assert not pm.isNull()
    assert not paint_dual_window_pixmap(
        primary_remaining=None, secondary_remaining=41.0, size=24
    ).isNull()


def test_webapp_html_and_api_handlers(monkeypatch) -> None:
    """Drive shipped Handler: GET / is HTML dashboard; /api/usage is JSON."""
    from http.client import HTTPConnection
    from threading import Thread
    from http.server import ThreadingHTTPServer

    from codexbar_gui.upstream import parse_upstream_item
    from codexbar_gui import webapp as web

    # Avoid live multi-provider + cost hang in unit tests
    fake = [
        parse_upstream_item(
            {
                "provider": "codex",
                "source": "oauth",
                "usage": {
                    "primary": {
                        "usedPercent": 1,
                        "windowMinutes": 300,
                        "resetsAt": "2099-01-01T00:00:00Z",
                    },
                    "secondary": {
                        "usedPercent": 0,
                        "windowMinutes": 10080,
                        "resetsAt": "2099-07-01T00:00:00Z",
                    },
                },
            }
        )
    ]
    monkeypatch.setattr(web, "fetch_enabled_providers", lambda timeout=35.0: fake)
    monkeypatch.setattr(web, "fetch_cost", lambda **kwargs: None)

    payload = web._views_to_json()
    assert "providers" in payload
    assert payload["providers"]

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
    port = httpd.server_address[1]
    t = Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        assert resp.status == 200
        assert "text/html" in (resp.getheader("Content-Type") or "")
        assert "CodexBar" in body
        assert "<html" in body.lower()
        assert "costHtml" in body or "Cost" in body or "Refresh" in body
        # Provider tabs must be interactive (not decorative spans)
        assert "data-filter" in body
        assert "setFilter" in body
        assert 'data-filter="all"' in body
        assert "data-provider=" in body
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        health = resp.read().decode()
        assert resp.status == 200
        assert "codexbar-gui-web" in health
        conn.close()

        # Drop-in for aipc-usage / Hermes quota MCP (replaces :8080 /usage)
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/usage")
        resp = conn.getresponse()
        usage_body = resp.read().decode()
        assert resp.status == 200
        import json as _json

        rows = _json.loads(usage_body)
        assert isinstance(rows, list) and rows
        assert "provider" in rows[0] and "snapshot" in rows[0]
        assert rows[0]["snapshot"].get("status") in ("ok", "error")
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/usage")
        resp = conn.getresponse()
        api = resp.read().decode()
        assert resp.status == 200
        assert "providers" in api
        assert "codex" in api
        conn.close()
    finally:
        httpd.shutdown()
