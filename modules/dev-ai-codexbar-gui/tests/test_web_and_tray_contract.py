"""Gating contracts for web HTML surface, tray paint, Wayland popover path."""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_primary_usage_ui_not_qmenu_popup() -> None:
    """Tray primary path is UsagePopover (QWidget Tool), not QMenu.popup."""
    tray = (GUI_DIR / "codexbar_gui" / "tray_app.py").read_text()
    pop = (GUI_DIR / "codexbar_gui" / "popover.py").read_text()
    assert "from codexbar_gui.popover import UsagePopover" in tray
    assert "UsagePopover" in tray
    assert "setContextMenu" not in tray or "Do NOT use setContextMenu" in tray
    assert ".popup(" not in tray
    # Popover documents / avoids grabbing popup; class is QWidget Tool window.
    assert "class UsagePopover(QWidget)" in pop
    assert "QMenu.popup" in pop  # docstring warning only
    assert "class UsagePopover(QMenu)" not in pop


def test_paint_remaining_digits_non_null() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.icon_updater import paint_usage_pixmap

    _ = QApplication.instance() or QApplication([])
    pm = paint_usage_pixmap(remaining=68.0, size=32)
    assert not pm.isNull()
    assert pm.width() >= 32
    assert pm.height() >= 32
    # Must actually paint pixels (not fully transparent empty icon)
    img = pm.toImage()
    opaque = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if img.pixelColor(x, y).alpha() > 0:
                opaque += 1
    assert opaque > 20


def test_webapp_html_and_api_handlers() -> None:
    """Drive shipped Handler: GET / is HTML dashboard; /api/usage is JSON."""
    from http.client import HTTPConnection
    from threading import Thread
    from http.server import ThreadingHTTPServer

    from codexbar_gui.webapp import _Handler, _views_to_json

    # Offline shape of API payload builder (CLI may or may not work)
    payload = _views_to_json()
    assert "providers" in payload
    assert "source" in payload

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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
        assert "not found" not in body.lower() or "JSON-only" in body
        assert "<html" in body.lower()
        assert "headline" in body
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        health = resp.read().decode()
        assert resp.status == 200
        assert "codexbar-gui-web" in health
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=45)
        conn.request("GET", "/api/usage")
        resp = conn.getresponse()
        api = resp.read().decode()
        assert resp.status == 200
        assert "providers" in api
        conn.close()
    finally:
        httpd.shutdown()
