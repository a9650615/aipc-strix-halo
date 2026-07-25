from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aipc_portal import HOST, PORT
from aipc_portal.agents import (
    agents_snapshot,
    get_delegation,
    get_kanban,
    log_tail,
    resolve_hermes_home,
)
from aipc_portal.dashboard import device_snapshot, snapshot
from aipc_portal.http_cache import TtlCache
from aipc_portal.registry import render, start_baseline_services, start_service
from aipc_portal.scheduling import scheduling_snapshot_cached

_AGENTS_CACHE = TtlCache(ttl_s=3.0)
_DASH_CACHE = TtlCache(ttl_s=2.5)

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
MEM0_BASE = "http://127.0.0.1:7000"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


def _services_roots() -> list[Path] | None:
    raw = os.environ.get("AIPC_PORTAL_SERVICES", "").strip()
    if not raw:
        return None
    roots = [Path(p) for p in raw.split(":") if p]
    return roots or None


def _safe_id(value: str) -> bool:
    return bool(value) and all(c.isalnum() or c in "-_" for c in value)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            self._send(200, "text/plain; charset=utf-8", b"ok\n")
            return
        if path == "/api/v1/dashboard":
            _value, body, etag = _DASH_CACHE.get_or_build(snapshot)
            self._send_json_cached(body, etag)
            return
        if path == "/api/v1/device/events":
            self._stream_device_events()
            return
        if path == "/api/v1/memories/facets":
            self._proxy_mem0("/memories/facets")
            return
        if path == "/api/v1/memories":
            self._proxy_mem0("/memories" + (f"?{parsed.query}" if parsed.query else ""))
            return
        if path == "/api/v1/agents":
            _value, body, etag = _AGENTS_CACHE.get_or_build(agents_snapshot)
            self._send_json_cached(body, etag)
            return
        if path == "/api/v1/models":
            _value, body, etag = scheduling_snapshot_cached()
            self._send_json_cached(body, etag)
            return
        if path.startswith("/api/v1/agents/delegations/"):
            delegation_id = path[len("/api/v1/agents/delegations/") :].strip("/")
            if delegation_id and _safe_id(delegation_id):
                detail = get_delegation(resolve_hermes_home(), delegation_id)
                if detail is None:
                    self._send(404, "application/json; charset=utf-8", b'{"detail":"not found"}')
                    return
                self._send(200, "application/json; charset=utf-8", json.dumps(detail).encode())
                return
            self._send(404, "application/json; charset=utf-8", b'{"detail":"not found"}')
            return
        if path.startswith("/api/v1/agents/kanban/"):
            task_id = path[len("/api/v1/agents/kanban/") :].strip("/")
            if task_id and _safe_id(task_id):
                detail = get_kanban(resolve_hermes_home(), task_id)
                if detail is None:
                    self._send(404, "application/json; charset=utf-8", b'{"detail":"not found"}')
                    return
                self._send(200, "application/json; charset=utf-8", json.dumps(detail).encode())
                return
            self._send(404, "application/json; charset=utf-8", b'{"detail":"not found"}')
            return
        if path == "/api/v1/agents/logs":
            qs = parse_qs(parsed.query or "")
            query = (qs.get("q") or [""])[0]
            try:
                limit = int((qs.get("limit") or ["120"])[0])
            except ValueError:
                limit = 120
            body = {
                "logs": log_tail(resolve_hermes_home(), query=query, limit=limit),
                "query": query,
            }
            self._send(200, "application/json; charset=utf-8", json.dumps(body).encode())
            return
        if self._send_static(path):
            return
        if path in ("/", "/index.html"):
            body = render(roots=_services_roots()).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
            return
        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/v1/memories/"):
            memory_id = path[len("/api/v1/memories/") :].strip("/")
            if memory_id and _safe_id(memory_id):
                self._proxy_mem0(f"/memories/{memory_id}", method="DELETE")
                return
        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def _send_static(self, path: str) -> bool:
        candidate = (STATIC_ROOT / path.lstrip("/")).resolve()
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if candidate.is_file() and STATIC_ROOT in candidate.parents:
            self._send(200, STATIC_TYPES.get(candidate.suffix, "application/octet-stream"), candidate.read_bytes())
            return True
        return False

    def _proxy_mem0(self, upstream: str, method: str = "GET", body: bytes | None = None) -> None:
        req = urllib.request.Request(
            MEM0_BASE + upstream,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                self._send(response.status, "application/json; charset=utf-8", response.read())
        except urllib.error.HTTPError as error:
            self._send(error.code, "application/json; charset=utf-8", error.read())
        except (urllib.error.URLError, OSError, TimeoutError):
            self._send(502, "application/json; charset=utf-8", b'{"detail": "mem0 unavailable"}')

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/memories/search":
            length = int(self.headers.get("Content-Length") or 0)
            self._proxy_mem0("/search", method="POST", body=self.rfile.read(length) if length else b"{}")
            return
        if path.startswith("/automation/") and path.endswith("/cancel"):
            task_id = path[len("/automation/") : -len("/cancel")].strip("/")
            if task_id and _safe_id(task_id):
                req = urllib.request.Request(
                    f"http://127.0.0.1:4100/automation/{task_id}/cancel",
                    data=b"",
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=2):
                        self._redirect("/")
                        return
                except urllib.error.URLError:
                    self._send(502, "text/plain; charset=utf-8", b"cancel failed\n")
                    return
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return

        if path.startswith("/services/") and path.endswith("/start"):
            service_id = path[len("/services/") : -len("/start")].strip("/")
            if service_id and _safe_id(service_id):
                ok, detail = start_service(service_id, roots=_services_roots())
                if ok:
                    self._redirect("/")
                    return
                self._send(
                    502,
                    "text/plain; charset=utf-8",
                    f"start failed: {detail}\n".encode("utf-8"),
                )
                return
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return

        if path == "/ops/baseline/start":
            results = start_baseline_services(roots=_services_roots())
            if not results:
                self._send(
                    404,
                    "text/plain; charset=utf-8",
                    b"no baseline units declared\n",
                )
                return
            # Partial success still redirects — degraded units surface on refresh.
            self._redirect("/")
            return

        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json_cached(self, body: bytes, etag: str) -> None:
        """304 when client ETag matches — saves bandwidth and avoids SPA repaint."""
        inm = (self.headers.get("If-None-Match") or "").strip()
        if inm and inm == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _stream_device_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        previous = ""
        try:
            for _ in range(120):
                current = json.dumps(device_snapshot(), sort_keys=True)
                if current != previous:
                    self.wfile.write(f"data: {current}\n\n".encode())
                    self.wfile.flush()
                    previous = current
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            return


def main(host: str = HOST, port: int = PORT) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
