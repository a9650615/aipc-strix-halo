from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aipc_portal import HOST, PORT
from aipc_portal.registry import render


def _services_roots() -> list[Path] | None:
    raw = os.environ.get("AIPC_PORTAL_SERVICES", "").strip()
    if not raw:
        return None
    roots = [Path(p) for p in raw.split(":") if p]
    return roots or None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send(200, "text/plain; charset=utf-8", b"ok\n")
            return
        if path in ("/", "/index.html"):
            body = render(roots=_services_roots()).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
            return
        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(host: str = HOST, port: int = PORT) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
