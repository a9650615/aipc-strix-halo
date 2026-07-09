"""HTTP server for serving usage/cost data to waybar, GNOME, KDE extensions.

Endpoints:
  GET /health   — {"status": "ok", "version": "..."}
  GET /usage    — JSON array of usage snapshots (optionally filtered by ?provider=)
  GET /cost     — JSON array of cost snapshots (optionally filtered by ?provider=)

Usage data is cached in memory and refreshed on each request (simple, no background
thread — matches CodexBar's serve behavior for external integrations).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from codexbar_usage import __version__
from codexbar_usage.cost import cost_results_for_cli
from codexbar_usage.fetch import fetch_all_usage, fetch_provider_usage

logger = logging.getLogger(__name__)


_DEFAULT_PORT = 8080
_DEFAULT_REFRESH_INTERVAL = 60


def _fetch_all_usage(providers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    return fetch_all_usage(providers=providers)


def _fetch_provider_usage(provider_id: str) -> Dict[str, Any]:
    return fetch_provider_usage(provider_id)


def _fetch_all_cost(providers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if providers:
        out: List[Dict[str, Any]] = []
        for pid in providers:
            out.extend(cost_results_for_cli(provider=pid))
        return out
    return cost_results_for_cli()


class _UsageHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the usage server."""

    server_version = f"codexbar-usage/{__version__}"

    def log_message(self, format, *args):
        sys.stderr.write(f"[usage-server] {format % args}\n")

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path == "/health":
            self._send_json({
                "status": "ok",
                "version": __version__,
                "uptime_seconds": int(time.time() - _start_time),
            })
        elif path == "/usage":
            provider_filter = params.get("provider", [None])[0]
            providers = [provider_filter] if provider_filter else None
            data = _fetch_all_usage(providers)
            self._send_json(data)
        elif path == "/cost":
            provider_filter = params.get("provider", [None])[0]
            providers = [provider_filter] if provider_filter else None
            data = _fetch_all_cost(providers)
            self._send_json(data)
        elif path == "/" or path == "":
            body = _HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_json({"error": "not found", "path": path}, status=404)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


_start_time = time.time()

_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>aipc usage</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #c9d1d9; --dim: #8b949e; --green: #3fb950;
    --yellow: #d29922; --red: #f85149; --blue: #58a6ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--text); padding: 1rem; }
  header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  header h1 { font-size: 1.4rem; }
  header .status { font-size: .85rem; color: var(--dim); }
  header .refresh { background: var(--blue); color: #fff; border: none; border-radius: 6px;
                    padding: .35rem .8rem; cursor: pointer; font-size: .85rem; }
  header .refresh:hover { opacity: .85; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
  .card .title { font-size: 1rem; font-weight: 600; margin-bottom: .5rem; display: flex;
                  justify-content: space-between; align-items: center; }
  .card .title .badge { font-size: .7rem; padding: .15rem .5rem; border-radius: 999px; }
  .badge.ok    { background: #238636; color: #fff; }
  .badge.warn  { background: #9e6a03; color: #fff; }
  .badge.fail  { background: #da3633; color: #fff; }
  .badge.dim   { background: #30363d; color: var(--dim); }
  .card .account { font-size: .78rem; color: var(--dim); margin-bottom: .4rem; }
  .bar-wrap { height: 18px; background: var(--border); border-radius: 4px; overflow: hidden;
              position: relative; margin: .3rem 0; }
  .bar-fill { height: 100%; transition: width .4s ease; }
  .bar-fill.low  { background: var(--green); }
  .bar-fill.mid  { background: var(--yellow); }
  .bar-fill.high { background: var(--red); }
  .bar-label { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
               font-size: .7rem; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,.6); }
  .meta { font-size: .78rem; color: var(--dim); margin-top: .3rem; }
  .meta .cyan { color: var(--blue); }
  .cost { color: var(--green); font-weight: 500; }
  .empty { text-align: center; padding: 4rem 1rem; color: var(--dim); }
  .empty .icon { font-size: 2.5rem; margin-bottom: .5rem; }
  footer { text-align: center; margin-top: 2rem; font-size: .75rem; color: var(--dim); }
</style>
</head>
<body>
<header>
  <h1>⚡ aipc usage</h1>
  <span class="status" id="status">Loading…</span>
  <button class="refresh" id="refreshBtn">Refresh</button>
</header>
<div id="app" class="grid"></div>
<footer>aipc-usage · codexbar port for Linux</footer>

<script>
const API = location.origin;
const REFRESH_MS = 60000;
let timer = null;

async function fetchJson(path) {
  const r = await fetch(API + path);
  return r.ok ? r.json() : { error: r.statusText };
}

function usageBar(pct) {
  const clamped = Math.min(Math.max(pct, 0), 100);
  let cls = 'low';
  if (clamped >= 80) cls = 'high';
  else if (clamped >= 50) cls = 'mid';
  return `<div class="bar-wrap"><div class="bar-fill ${cls}" style="width:${clamped}%"></div>
          <div class="bar-label">${clamped.toFixed(0)}%</div></div>`;
}

function badge(status) {
  let cls = 'dim';
  if (status === 'configured') cls = 'ok';
  else if (status === 'no-api-key' || status === 'fetching') cls = 'warn';
  else if (status === 'error' || status === 'failed') cls = 'fail';
  return `<span class="badge ${cls}">${status}</span>`;
}

function renderCard(provider, snapshot) {
  const name = snapshot.display_name || provider;
  const primary = snapshot.primary || {};
  const usedPct = (primary.used_percent ?? 0) * 100;
  const windowMin = primary.window_minutes;
  const resetDesc = primary.reset_description || '';
  const account = snapshot.identity?.account_email || '';
  const cost = snapshot.provider_cost;

  let html = `<div class="card">
    <div class="title"><span>${name}</span>${badge(snapshot.status)}</div>`;
  if (account) html += `<div class="account">👤 ${account}</div>`;
  html += usageBar(usedPct);
  if (windowMin) html += `<div class="meta">Window: ${windowMin} min</div>`;
  if (resetDesc) html += `<div class="meta">Resets: <span class="cyan">${resetDesc}</span></div>`;
  if (cost) html += `<div class="meta">Cost: <span class="cost">$${cost.total.toFixed(4)}</span></div>`;
  html += `</div>`;
  return html;
}

async function load() {
  const data = await fetchJson('/usage');
  const app = document.getElementById('app');
  const status = document.getElementById('status');
  if (data.error) {
    app.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>${data.error}</p></div>`;
    status.textContent = 'Error';
    return;
  }
  if (!Array.isArray(data) || data.length === 0) {
    app.innerHTML = `<div class="empty"><div class="icon">📭</div><p>No providers configured.<br>
      Run \`aipc-usage config set-api-key --provider <name>\` to add one.</p></div>`;
    status.textContent = 'No providers';
    return;
  }
  status.textContent = `${data.length} providers · ${new Date().toLocaleTimeString()}`;
  app.innerHTML = data.map(d => renderCard(d.provider, d.snapshot)).join('');
}

document.getElementById('refreshBtn').addEventListener('click', load);
load();
timer = setInterval(load, REFRESH_MS);
</script>
</body>
</html>
"""


def run_server(port: int = _DEFAULT_PORT, refresh_interval: int = _DEFAULT_REFRESH_INTERVAL, host: str = "127.0.0.1") -> None:
    """Start the usage HTTP server. Blocks until interrupted."""
    server = ThreadingHTTPServer((host, port), _UsageHandler)
    _console_startup(port, refresh_interval)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def run_server_in_thread(port: int = _DEFAULT_PORT, refresh_interval: int = _DEFAULT_REFRESH_INTERVAL, host: str = "127.0.0.1") -> "threading.Thread":
    """Start the server in a background thread. Returns the thread handle."""
    import threading
    t = threading.Thread(target=run_server, args=(port, refresh_interval, host), daemon=True)
    t.start()
    return t


def _console_startup(port: int, refresh_interval: int) -> None:
    from rich.console import Console
    c = Console()
    c.print(f"[green]codexbar-usage server[/green] running on [bold]http://127.0.0.1:{port}[/bold]")
    c.print(f"  [dim]refresh interval:[/dim] {refresh_interval}s  [dim]endpoints:[/dim] /health /usage /cost")
    c.print("  [dim]Press Ctrl+C to stop[/dim]")
