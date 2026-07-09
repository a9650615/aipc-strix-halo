"""Local web dashboard for CodexBar (official CLI is still the data plane).

Official ``codexbar serve`` only exposes JSON endpoints (``/`` is 404).
This tiny stdlib HTTP server serves a readable HTML UI that loads
``/api/usage`` from the same process, which shells out to ``codexbar usage``.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from codexbar_gui.upstream import fetch_from_cli, find_codexbar_binary, parse_upstream_list

logger = logging.getLogger("codexbar_gui.webapp")

DEFAULT_WEB_PORT = 8787
DEFAULT_WEB_HOST = "127.0.0.1"

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>CodexBar</title>
<style>
  :root {
    --bg: #11111b; --card: #1e1e2e; --border: #313244; --text: #cdd6f4;
    --muted: #a6adc8; --green: #a6e3a1; --yellow: #f9e2af; --red: #f38ba8;
    --teal: #94e2d5; --blue: #89b4fa;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: ui-sans-serif, system-ui, sans-serif;
    background: var(--bg); color: var(--text); padding: 1.25rem;
  }
  header {
    display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
    margin-bottom: 1.25rem;
  }
  header h1 { font-size: 1.35rem; margin: 0; letter-spacing: .02em; }
  header .meta { color: var(--muted); font-size: .85rem; }
  button {
    background: #313244; color: var(--text); border: 0; border-radius: 8px;
    padding: .45rem .9rem; cursor: pointer; font-size: .9rem;
  }
  button:hover { background: #45475a; }
  .grid {
    display: grid; gap: 1rem;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 1rem 1.1rem;
  }
  .card h2 {
    margin: 0 0 .75rem; font-size: 1.05rem;
    display: flex; justify-content: space-between; align-items: baseline; gap: .5rem;
  }
  .card h2 .src { color: var(--muted); font-size: .75rem; font-weight: 500; }
  .err { color: var(--red); font-size: .9rem; line-height: 1.35; }
  .win { margin: .55rem 0; }
  .win .row { display: flex; justify-content: space-between; font-size: .85rem; margin-bottom: .25rem; }
  .win .lab { color: var(--muted); }
  .win .pct { font-variant-numeric: tabular-nums; font-weight: 600; }
  .bar {
    height: 10px; background: #313244; border-radius: 999px; overflow: hidden;
  }
  .bar > i {
    display: block; height: 100%; border-radius: 999px;
    background: var(--green); width: 0%; transition: width .35s ease;
  }
  .bar.mid > i { background: var(--yellow); }
  .bar.low > i { background: var(--red); }
  .pace { color: var(--teal); font-size: .8rem; margin-top: .65rem; line-height: 1.35; }
  .foot { color: var(--muted); font-size: .78rem; margin-top: .65rem; }
  .empty { color: var(--muted); padding: 2rem; text-align: center; }
  .big {
    font-size: 2rem; font-weight: 700; font-variant-numeric: tabular-nums;
    color: var(--blue); margin: 0 .25rem 0 0;
  }
</style>
</head>
<body>
<header>
  <h1>CodexBar</h1>
  <span class="big" id="headline">—</span>
  <span class="meta">% left (worst)</span>
  <span class="meta" id="meta">loading…</span>
  <button type="button" id="refresh">Refresh</button>
</header>
<p class="meta" style="margin:-.5rem 0 1rem">
  This is the HTML UI on <strong>:8787</strong>. Official <code>codexbar serve</code>
  on :8080 is JSON-only (<code>GET /</code> → 404) — that is not a missing UI.
</p>
<div id="root" class="grid"></div>
<script>
function colorClass(rem) {
  if (rem == null) return '';
  if (rem <= 20) return 'low';
  if (rem <= 50) return 'mid';
  return '';
}
function winHtml(w) {
  if (!w) return '';
  const rem = w.remaining_percent;
  const cls = colorClass(rem);
  const pct = rem == null ? '—' : Math.round(rem) + '% left';
  const used = rem == null ? 0 : rem;
  return `<div class="win">
    <div class="row"><span class="lab">${w.label}</span>
      <span class="pct">${pct}</span></div>
    <div class="bar ${cls}"><i style="width:${used}%"></i></div>
    <div class="row"><span class="lab">${w.reset_description || ''}</span>
      <span class="lab">${w.window_minutes ? w.window_minutes + 'm window' : ''}</span></div>
  </div>`;
}
function card(p) {
  if (p.error) {
    return `<article class="card"><h2>${p.display_name || p.provider}
      <span class="src">${p.source || ''}</span></h2>
      <div class="err">${p.error}</div></article>`;
  }
  const rem = p.headline_remaining;
  const big = rem == null ? '' : `<span class="big">${Math.round(rem)}%</span><span class="meta">left</span>`;
  const meta = [p.account, p.plan ? 'plan:' + p.plan : null,
    p.credits_remaining != null ? 'credits:' + p.credits_remaining : null]
    .filter(Boolean).join(' · ');
  return `<article class="card">
    <h2><span>${p.display_name || p.provider} ${big}</span>
      <span class="src">${p.source || ''}</span></h2>
    ${winHtml(p.primary)}
    ${winHtml(p.secondary)}
    ${winHtml(p.tertiary)}
    ${p.pace_summary ? `<div class="pace">${p.pace_summary}</div>` : ''}
    ${meta ? `<div class="foot">${meta}</div>` : ''}
  </article>`;
}
async function load() {
  const meta = document.getElementById('meta');
  const root = document.getElementById('root');
  const headline = document.getElementById('headline');
  meta.textContent = 'loading…';
  try {
    const r = await fetch('/api/usage', {cache: 'no-store'});
    const data = await r.json();
    if (!data.providers || !data.providers.length) {
      root.innerHTML = `<div class="empty">${data.detail || 'No providers'}</div>`;
      headline.textContent = '—';
    } else {
      root.innerHTML = data.providers.map(card).join('');
      const rems = data.providers
        .map(p => p.headline_remaining)
        .filter(x => x != null && !Number.isNaN(x));
      headline.textContent = rems.length ? Math.round(Math.min(...rems)) : '—';
    }
    meta.textContent = (data.source || 'cli') + ' · ' + new Date().toLocaleTimeString();
  } catch (e) {
    root.innerHTML = `<div class="empty err">Failed to load: ${e}</div>`;
    meta.textContent = 'error';
    headline.textContent = '—';
  }
}
document.getElementById('refresh').onclick = load;
load();
setInterval(load, 60000);
</script>
</body>
</html>
"""


def _views_to_json() -> dict:
    views = fetch_from_cli() or []
    providers = []
    for v in views:
        providers.append(
            {
                "provider": v.provider,
                "display_name": v.display_name,
                "source": v.source,
                "error": v.error,
                "account": v.account,
                "plan": v.plan,
                "credits_remaining": v.credits_remaining,
                "pace_summary": v.pace_summary,
                "headline_remaining": v.headline_remaining,
                "primary": None
                if not v.primary
                else {
                    "label": v.primary.label,
                    "used_percent": v.primary.used_percent,
                    "remaining_percent": v.primary.remaining_percent,
                    "reset_description": v.primary.reset_description,
                    "window_minutes": v.primary.window_minutes,
                },
                "secondary": None
                if not v.secondary
                else {
                    "label": v.secondary.label,
                    "used_percent": v.secondary.used_percent,
                    "remaining_percent": v.secondary.remaining_percent,
                    "reset_description": v.secondary.reset_description,
                    "window_minutes": v.secondary.window_minutes,
                },
                "tertiary": None
                if not v.tertiary
                else {
                    "label": v.tertiary.label,
                    "used_percent": v.tertiary.used_percent,
                    "remaining_percent": v.tertiary.remaining_percent,
                    "reset_description": v.tertiary.reset_description,
                    "window_minutes": v.tertiary.window_minutes,
                },
            }
        )
    binary = find_codexbar_binary()
    if not providers:
        return {
            "providers": [],
            "source": "cli",
            "detail": (
                "No data from official codexbar CLI. "
                f"binary={binary or 'MISSING'}"
            ),
        }
    return {"providers": providers, "source": f"cli:{binary}"}


class _Handler(BaseHTTPRequestHandler):
    server_version = "codexbar-gui-web/0.3"

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._send(200, _HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/usage":
            try:
                payload = _views_to_json()
            except Exception as exc:
                payload = {"providers": [], "detail": str(exc), "source": "error"}
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(200, raw, "application/json; charset=utf-8")
            return
        if path == "/health":
            raw = json.dumps(
                {
                    "status": "ok",
                    "role": "codexbar-gui-web",
                    "binary": find_codexbar_binary(),
                }
            ).encode()
            self._send(200, raw, "application/json; charset=utf-8")
            return
        self._send(
            404,
            json.dumps({"error": "not found", "hint": "GET / or /api/usage"}).encode(),
            "application/json; charset=utf-8",
        )


_httpd: Optional[ThreadingHTTPServer] = None
_thread: Optional[threading.Thread] = None


def start_web(
    host: str = DEFAULT_WEB_HOST,
    port: int = DEFAULT_WEB_PORT,
) -> tuple[bool, str]:
    """Start background web UI. Returns (ok, url_or_error)."""
    global _httpd, _thread
    if _httpd is not None:
        return True, f"http://{host}:{_httpd.server_address[1]}/"

    try:
        httpd = ThreadingHTTPServer((host, port), _Handler)
    except OSError as exc:
        # Port busy — try a few alternatives
        for alt in (port + 1, port + 2, 8790, 8791):
            try:
                httpd = ThreadingHTTPServer((host, alt), _Handler)
                port = alt
                break
            except OSError:
                httpd = None  # type: ignore
        if httpd is None:
            return False, f"bind failed: {exc}"

    _httpd = httpd

    def _run() -> None:
        logger.info("web UI on http://%s:%s/", host, httpd.server_address[1])
        httpd.serve_forever(poll_interval=0.5)

    _thread = threading.Thread(target=_run, name="codexbar-gui-web", daemon=True)
    _thread.start()
    return True, f"http://{host}:{httpd.server_address[1]}/"


def stop_web() -> None:
    global _httpd, _thread
    if _httpd is not None:
        _httpd.shutdown()
        _httpd = None
    _thread = None


def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="CodexBar local web dashboard")
    ap.add_argument("--host", default=DEFAULT_WEB_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_WEB_PORT)
    args = ap.parse_args()
    ok, msg = start_web(args.host, args.port)
    if not ok:
        print(msg)
        return 1
    print(f"CodexBar web UI: {msg}")
    print("Data from official `codexbar usage` CLI.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        stop_web()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
