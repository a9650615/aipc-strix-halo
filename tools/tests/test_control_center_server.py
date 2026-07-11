from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path


PORTAL_LIB = Path(__file__).parents[2] / "modules/system-aipc-portal/files/usr/lib/aipc-portal"
sys.path.insert(0, str(PORTAL_LIB))

from aipc_portal import server  # noqa: E402


def test_portal_serves_spa_and_dashboard_api(tmp_path: Path, monkeypatch) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>Control Center</h1>", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_ROOT", static)
    monkeypatch.setattr(server, "snapshot", lambda: {"summary": "ready"})
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        assert urllib.request.urlopen(f"{base}/").read() == b"<h1>Control Center</h1>"
        assert json.load(urllib.request.urlopen(f"{base}/api/v1/dashboard")) == {"summary": "ready"}
    finally:
        httpd.shutdown()
        thread.join()


def test_portal_streams_device_state(monkeypatch) -> None:
    monkeypatch.setattr(server, "device_snapshot", lambda: {"availability": "available"})
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        response = urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/api/v1/device/events", timeout=2)
        assert json.loads(response.readline().removeprefix(b"data: ")) == {"availability": "available"}
        response.close()
    finally:
        httpd.shutdown()
        thread.join()
