from __future__ import annotations

import json
import sys
import threading
import urllib.error
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


def test_portal_serves_static_subpages_and_blocks_traversal(tmp_path: Path, monkeypatch) -> None:
    static = tmp_path / "static"
    (static / "memory").mkdir(parents=True)
    (static / "memory" / "index.html").write_text("<h1>Memory</h1>", encoding="utf-8")
    (static / "_astro").mkdir()
    (static / "_astro" / "app.js").write_text("export {}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_ROOT", static)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        assert urllib.request.urlopen(f"{base}/memory").read() == b"<h1>Memory</h1>"
        response = urllib.request.urlopen(f"{base}/_astro/app.js")
        assert response.headers["Content-Type"].startswith("application/javascript")
        try:
            urllib.request.urlopen(f"{base}/memory/../../secret.txt")
            raised = False
        except urllib.error.HTTPError as error:
            raised = error.code == 404
        assert raised
    finally:
        httpd.shutdown()
        thread.join()


def test_portal_proxies_mem0_list_search_delete(monkeypatch) -> None:
    calls: list[tuple[str, str, bytes]] = []

    class FakeMem0(server.BaseHTTPRequestHandler):
        def _record(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            calls.append((self.command, self.path, self.rfile.read(length)))
            body = b'{"results": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_DELETE = _record

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    upstream = server.ThreadingHTTPServer(("127.0.0.1", 0), FakeMem0)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    monkeypatch.setattr(server, "MEM0_BASE", f"http://127.0.0.1:{upstream.server_port}")
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        assert json.load(urllib.request.urlopen(f"{base}/api/v1/memories?user_id=u&limit=5")) == {"results": []}
        search = urllib.request.Request(
            f"{base}/api/v1/memories/search",
            data=b'{"query": "q"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        assert json.load(urllib.request.urlopen(search)) == {"results": []}
        delete = urllib.request.Request(f"{base}/api/v1/memories/mem-1", method="DELETE")
        assert json.load(urllib.request.urlopen(delete)) == {"results": []}
        assert calls == [
            ("GET", "/memories?user_id=u&limit=5", b""),
            ("POST", "/search", b'{"query": "q"}'),
            ("DELETE", "/memories/mem-1", b""),
        ]
    finally:
        httpd.shutdown()
        upstream.shutdown()
        thread.join()
        upstream_thread.join()
