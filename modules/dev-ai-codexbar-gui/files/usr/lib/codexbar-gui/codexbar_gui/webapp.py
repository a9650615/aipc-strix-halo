"""Local web dashboard for CodexBar (official CLI is still the data plane).

Layout mirrors official CodexBar provider panel: Session/Weekly with
``% left`` + ``Resets in …``, pace, credits, account/plan.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

from codexbar_gui.upstream import fetch_from_cli, find_codexbar_binary

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
    --bg: #0b0b12; --card: #1e1e2e; --border: #313244; --text: #cdd6f4;
    --muted: #a6adc8; --dim: #6c7086; --green: #a6e3a1; --yellow: #fab387;
    --red: #f38ba8; --teal: #94e2d5; --cyan: #89dceb; --purple: #cba6f7;
    --blue: #89b4fa;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, #1e1e2e 0%, var(--bg) 55%);
    color: var(--text); min-height: 100vh; padding: 1.5rem;
  }
  header {
    display: flex; flex-wrap: wrap; gap: .75rem 1rem; align-items: center;
    margin-bottom: 1rem;
  }
  header h1 { font-size: 1.25rem; margin: 0; font-weight: 700; letter-spacing: .01em; }
  .meta { color: var(--muted); font-size: .85rem; }
  .dim { color: var(--dim); font-size: .8rem; }
  button {
    background: #313244; color: var(--text); border: 0; border-radius: 8px;
    padding: .5rem 1rem; cursor: pointer; font-size: .9rem;
  }
  button:hover { background: #45475a; }
  .tabs { display: flex; gap: .5rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .tab {
    background: #313244; color: var(--text); border-radius: 999px;
    padding: .35rem .9rem; font-size: .85rem; font-weight: 600;
  }
  .tab.active { background: #45475a; box-shadow: inset 0 0 0 1px #585b70; }
  .grid {
    display: grid; gap: 1.1rem;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  }
  .card {
    background: linear-gradient(180deg, #222233 0%, var(--card) 40%);
    border: 1px solid var(--border); border-radius: 14px;
    padding: 1.1rem 1.2rem; box-shadow: 0 12px 40px rgba(0,0,0,.35);
  }
  .head {
    display: flex; justify-content: space-between; gap: 1rem;
    align-items: flex-start; margin-bottom: .85rem;
  }
  .head h2 { margin: 0; font-size: 1.2rem; }
  .head .sub { color: var(--dim); font-size: .78rem; margin-top: .2rem; }
  .right { text-align: right; }
  .account { color: var(--muted); font-size: .82rem; }
  .badge {
    display: inline-block; margin-top: .25rem; background: #313244;
    color: var(--purple); border-radius: 6px; padding: .15rem .55rem;
    font-size: .75rem; font-weight: 600;
  }
  .sec {
    color: var(--dim); font-size: .68rem; font-weight: 700;
    letter-spacing: .08em; text-transform: uppercase; margin: .85rem 0 .4rem;
  }
  .win { margin: .55rem 0 .75rem; }
  .win .row {
    display: flex; justify-content: space-between; align-items: baseline;
    gap: .5rem; margin-bottom: .3rem; font-size: .9rem;
  }
  .win .lab { font-weight: 600; min-width: 4.5rem; }
  .win .pct { color: var(--cyan); font-variant-numeric: tabular-nums; font-weight: 600; }
  .win .pct.mid { color: var(--yellow); }
  .win .pct.low { color: var(--red); }
  .win .resets { color: var(--muted); font-size: .8rem; }
  .bar {
    height: 8px; background: #313244; border-radius: 999px; overflow: hidden;
  }
  .bar > i {
    display: block; height: 100%; border-radius: 999px;
    background: var(--cyan); width: 0%; transition: width .35s ease;
  }
  .bar.mid > i { background: var(--yellow); }
  .bar.low > i { background: var(--red); }
  .used { color: var(--dim); font-size: .75rem; margin-top: .25rem; }
  .pace {
    font-size: .88rem; font-weight: 600; margin: .3rem 0 .15rem; line-height: 1.35;
  }
  .pace.reserve { color: var(--green); }
  .pace.deficit { color: var(--yellow); }
  .pace.on_pace { color: var(--teal); }
  .exp { color: var(--dim); font-size: .72rem; }
  .credits { display: flex; justify-content: space-between; gap: .75rem; font-size: .9rem; }
  .credits .muted { color: var(--muted); font-size: .8rem; }
  .err { color: var(--red); font-size: .9rem; line-height: 1.35; }
  .empty { color: var(--muted); padding: 2rem; text-align: center; }
  .note { color: var(--dim); font-size: .78rem; margin: 0 0 1rem; max-width: 52rem; line-height: 1.4; }
</style>
</head>
<body>
<header>
  <h1>CodexBar</h1>
  <span class="meta" id="meta">loading…</span>
  <button type="button" id="refresh">Refresh Now</button>
</header>
<p class="note">
  Usage dashboard on <strong>:8787</strong> (this page). Official
  <code>codexbar serve</code> on :8080 is JSON-only — not a missing UI.
  Layout follows official CodexBar provider panel fields from CLI JSON.
</p>
<div class="tabs" id="tabs"></div>
<div id="root" class="grid"></div>
<script>
function tone(rem) {
  if (rem == null) return '';
  if (rem <= 20) return 'low';
  if (rem <= 50) return 'mid';
  return '';
}
function winHtml(w) {
  if (!w) return '';
  const rem = w.remaining_percent;
  const used = w.used_percent;
  const t = tone(rem);
  const pct = rem == null ? '—' : Math.round(rem) + '% left';
  const fill = rem == null ? 0 : rem;
  const resets = w.resets_in || w.reset_description || '';
  const pace = w.pace;
  const paceHtml = pace ? `<div class="pace ${pace.status || ''}">${pace.summary}</div>
    <div class="exp">expected ~${Math.round(pace.expected_used_percent)}% used by now (linear)</div>` : '';
  return `<div class="win">
    <div class="row">
      <span class="lab">${w.label.replace(' (5h)','')}</span>
      <span class="pct ${t}">${pct}</span>
      <span class="resets">${resets}</span>
    </div>
    <div class="bar ${t}"><i style="width:${fill}%"></i></div>
    ${paceHtml}
    <div class="used">${used == null ? '' : Math.round(used) + '% used'}${w.reset_description && w.resets_in ? ' · ' + w.reset_description : ''}</div>
  </div>`;
}
function card(p) {
  if (p.error) {
    return `<article class="card"><div class="head"><div><h2>${p.display_name || p.provider}</h2>
      <div class="sub">${p.source || ''}</div></div></div>
      <div class="err">${p.error}</div></article>`;
  }
  const sub = [p.version, p.source, p.updated_label, p.data_confidence].filter(Boolean).join(' · ');
  return `<article class="card">
    <div class="head">
      <div>
        <h2>${p.display_name || p.provider}</h2>
        <div class="sub">${sub}</div>
      </div>
      <div class="right">
        ${p.account ? `<div class="account">${p.account}</div>` : ''}
        ${p.plan_label ? `<span class="badge">${p.plan_label}</span>` : ''}
      </div>
    </div>
    <div class="sec">Usage</div>
    ${winHtml(p.primary)}
    ${winHtml(p.secondary)}
    ${winHtml(p.tertiary)}
    <div class="sec">Credits</div>
    <div class="credits">
      <span>${p.credits_remaining != null ? p.credits_remaining + ' left' : '—'}</span>
      <span class="muted">${p.reset_credits_available != null
        ? 'Limit reset credits: ' + p.reset_credits_available + ' available' : ''}</span>
    </div>
  </article>`;
}
async function load() {
  const meta = document.getElementById('meta');
  const root = document.getElementById('root');
  const tabs = document.getElementById('tabs');
  meta.textContent = 'loading…';
  try {
    const r = await fetch('/api/usage', {cache: 'no-store'});
    const data = await r.json();
    if (!data.providers || !data.providers.length) {
      root.innerHTML = `<div class="empty">${data.detail || 'No providers'}</div>`;
      tabs.innerHTML = '';
    } else {
      tabs.innerHTML = data.providers.map((p,i) =>
        `<span class="tab ${i===0?'active':''}">${p.display_name || p.provider}</span>`).join('');
      root.innerHTML = data.providers.map(card).join('');
    }
    meta.textContent = (data.source || 'cli') + ' · ' + new Date().toLocaleTimeString();
  } catch (e) {
    root.innerHTML = `<div class="empty err">Failed to load: ${e}</div>`;
    meta.textContent = 'error';
  }
}
document.getElementById('refresh').onclick = load;
load();
setInterval(load, 60000);
</script>
</body>
</html>
"""


def _win_json(win) -> Optional[dict]:
    if win is None:
        return None
    pace = None
    if win.pace is not None:
        pace = {
            "reserve_percent": win.pace.reserve_percent,
            "expected_used_percent": win.pace.expected_used_percent,
            "will_last_to_reset": win.pace.will_last_to_reset,
            "summary": win.pace.summary,
            "status": win.pace.status,
            "source": win.pace.source,
        }
    return {
        "label": win.label,
        "used_percent": win.used_percent,
        "remaining_percent": win.remaining_percent,
        "reset_description": win.reset_description,
        "window_minutes": win.window_minutes,
        "resets_at": win.resets_at,
        "resets_in": win.resets_in,
        "pace": pace,
    }


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
                "plan_label": v.plan_label,
                "version": v.version,
                "credits_remaining": v.credits_remaining,
                "reset_credits_available": v.reset_credits_available,
                "data_confidence": v.data_confidence,
                "updated_at": v.updated_at,
                "updated_label": v.updated_label,
                "pace_summary": v.pace_summary,
                "headline_remaining": v.headline_remaining,
                "primary": _win_json(v.primary),
                "secondary": _win_json(v.secondary),
                "tertiary": _win_json(v.tertiary),
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
    server_version = "codexbar-gui-web/0.4"

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
