"""Local web dashboard for CodexBar (official CLI is still the data plane).

Layout mirrors official CodexBar provider panel: Session/Weekly with
``% left`` + ``Resets in …``, pace, credits, account/plan.
"""

from __future__ import annotations

import json
import logging
import threading
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

from codexbar_gui.cost import fetch_cost
from codexbar_gui.upstream import fetch_enabled_providers, find_codexbar_binary

logger = logging.getLogger("codexbar_gui.webapp")

# Canonical port — replaces legacy aipc-usage on :8080 (HTML + /usage JSON).
DEFAULT_WEB_PORT = 8080
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
    cursor: pointer; border: 0; user-select: none;
  }
  .tab:hover { background: #3f4155; }
  .tab.active { background: #45475a; box-shadow: inset 0 0 0 1px #585b70; }
  .card.hidden { display: none; }
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
  .barwrap { position: relative; margin: .25rem 0; }
  .bar {
    position: relative; height: 8px; background: #313244; border-radius: 999px;
    overflow: visible;
  }
  .bar > i.fill {
    display: block; height: 100%; border-radius: 999px;
    background: #f5a97f; width: 0%;
  }
  .bar.mid > i.fill { background: var(--yellow); }
  .bar.low > i.fill { background: var(--red); }
  .bar .tick {
    position: absolute; top: -3px; height: 14px; width: 2px;
    background: var(--green); border-radius: 1px; transform: translateX(-1px);
  }
  .used { color: var(--dim); font-size: .75rem; margin-top: .25rem; }
  .pace {
    font-size: .88rem; font-weight: 600; margin: .3rem 0 .15rem; line-height: 1.35;
  }
  .pace.reserve { color: var(--green); }
  .pace.deficit { color: var(--yellow); }
  .pace.on_pace { color: var(--teal); }
  .exp { color: var(--dim); font-size: .72rem; }
  .costbox {
    background: #181825; border-radius: 10px; padding: .75rem .9rem; margin-top: .5rem;
  }
  .chart {
    display: flex; align-items: flex-end; gap: 2px; height: 64px; margin-top: .5rem;
  }
  .chart i {
    flex: 1; background: #f5a97f; border-radius: 2px 2px 0 0; min-width: 3px;
  }
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
  Usage dashboard on <strong>:8080</strong> (this page). Replaces legacy
  <code>aipc-usage</code>. Official CLI data via <code>codexbar usage</code>.
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
  const t = tone(rem);
  const pct = rem == null ? '—' : Math.round(rem) + '% left';
  const fill = rem == null ? 0 : rem;
  const resets = w.resets_in || w.reset_description || '';
  const pace = w.pace;
  let shortPace = '';
  let lasts = '';
  if (pace) {
    if (pace.status === 'reserve') shortPace = Math.round(pace.reserve_percent) + '% in reserve';
    else if (pace.status === 'deficit') shortPace = Math.round(-pace.reserve_percent) + '% over pace';
    else shortPace = 'On pace';
    lasts = pace.will_last_to_reset ? 'Lasts until reset' : 'May run out early';
  }
  // expected remaining tick = 100 - expected_used
  const tick = pace && pace.expected_used_percent != null
    ? Math.max(0, Math.min(100, 100 - pace.expected_used_percent)) : null;
  return `<div class="win">
    <div class="row"><span class="lab">${w.label}</span></div>
    <div class="barwrap">
      <div class="bar ${t}"><i class="fill" style="width:${fill}%"></i>
        ${tick != null ? `<span class="tick" style="left:${tick}%"></span>` : ''}
      </div>
    </div>
    <div class="row">
      <div>
        <div class="pct ${t}">${pct}</div>
        ${shortPace ? `<div class="pace ${pace.status || ''}">${shortPace}</div>` : ''}
      </div>
      <div style="text-align:right">
        <div class="resets">${resets}</div>
        ${lasts ? `<div class="exp">${lasts}</div>` : ''}
      </div>
    </div>
  </div>`;
}
function costHtml(c) {
  if (!c || c.error) return c && c.error ? `<div class="sec">Cost</div><div class="err">${c.error}</div>` : '';
  const days = (c.daily || []).slice(-30);
  const peak = Math.max(0.01, ...days.map(d => d.total_cost || 0));
  const bars = days.map(d => {
    const h = Math.max(2, Math.round(56 * ((d.total_cost || 0) / peak)));
    return `<i style="height:${h}px" title="${d.date}: $${(d.total_cost||0).toFixed(2)}"></i>`;
  }).join('');
  return `<div class="sec">Cost</div>
    <div class="costbox">
      <div>Today: $${(c.today_cost||0).toFixed(2)} · ${fmtTok(c.today_tokens)} tokens</div>
      <div class="muted">Last ${c.history_days||30} days: $${(c.period_cost||0).toFixed(2)} · ${fmtTok(c.period_tokens)} tokens</div>
      ${days.length ? `<div class="chart">${bars}</div>` : ''}
    </div>`;
}
function fmtTok(n) {
  n = n || 0;
  if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
  return String(n);
}
function card(p) {
  const pid = (p.provider || '').toLowerCase();
  if (p.error) {
    return `<article class="card" data-provider="${pid}"><div class="head"><div><h2>${p.display_name || p.provider}</h2>
      <div class="sub">${p.source || ''}</div></div></div>
      <div class="err">${p.error}</div></article>`;
  }
  const sub = [p.updated_label, p.source].filter(Boolean).join(' · ');
  const extras = (p.extra_windows || []).map(winHtml).join('');
  // Only render windows that exist — no "missing limit" callouts.
  return `<article class="card" data-provider="${pid}">
    <div class="head">
      <div>
        <h2>${p.display_name || p.provider}</h2>
        <div class="sub">${sub}</div>
      </div>
      <div class="right">
        ${p.plan_label ? `<span class="badge">${p.plan_label}</span>` : ''}
        ${p.account ? `<div class="account">${p.account}</div>` : ''}
      </div>
    </div>
    ${winHtml(p.primary)}
    ${winHtml(p.secondary)}
    ${winHtml(p.tertiary)}
    ${extras}
    ${p.credits_remaining != null ? `<div class="sec">Credits</div>
      <div class="credits"><span>${p.credits_remaining} left</span></div>` : ''}
    ${costHtml(p.cost)}
  </article>`;
}
let activeFilter = 'all';
function setFilter(id) {
  activeFilter = id || 'all';
  document.querySelectorAll('#tabs .tab').forEach(t => {
    t.classList.toggle('active', t.dataset.filter === activeFilter);
  });
  document.querySelectorAll('#root .card').forEach(c => {
    const show = activeFilter === 'all' || c.dataset.provider === activeFilter;
    c.classList.toggle('hidden', !show);
  });
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
      const tabHtml = [`<button type="button" class="tab" data-filter="all">All</button>`]
        .concat(data.providers.map(p => {
          const id = (p.provider || '').toLowerCase();
          const label = p.display_name || p.provider;
          return `<button type="button" class="tab" data-filter="${id}">${label}</button>`;
        })).join('');
      tabs.innerHTML = tabHtml;
      tabs.querySelectorAll('.tab').forEach(t => {
        t.onclick = () => setFilter(t.dataset.filter);
      });
      root.innerHTML = data.providers.map(card).join('');
      // keep previous filter if still valid
      const still = activeFilter === 'all' ||
        data.providers.some(p => (p.provider || '').toLowerCase() === activeFilter);
      setFilter(still ? activeFilter : 'all');
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
    views = fetch_enabled_providers(timeout=35.0) or []
    providers = []
    for v in views:
        cost = None
        if v.ok:
            try:
                cv = fetch_cost(provider=v.provider, days=30, timeout=40.0)
            except Exception:
                cv = None
            if cv is not None:
                cost = {
                    "today_cost": cv.today_cost,
                    "today_tokens": cv.today_tokens,
                    "period_cost": cv.period_cost,
                    "period_tokens": cv.period_tokens,
                    "history_days": cv.history_days,
                    "error": cv.error,
                    "daily": [
                        {
                            "date": d.date,
                            "total_cost": d.total_cost,
                            "total_tokens": d.total_tokens,
                        }
                        for d in cv.daily
                    ],
                }
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
                "extra_windows": [_win_json(w) for w in v.extra_windows],
                "cost": cost,
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


def _provider_to_aipc_snapshot(p: dict) -> dict:
    """Map rich GUI provider JSON → aipc-usage / Hermes snapshot shape."""
    err = p.get("error")
    status = "error" if err else "ok"
    identity: dict = {}
    if p.get("account"):
        identity["email"] = p["account"]
    if p.get("plan") or p.get("plan_label"):
        identity["plan"] = p.get("plan_label") or p.get("plan")
    snap = {
        "provider": p.get("provider"),
        "display_name": p.get("display_name") or p.get("provider"),
        "status": status,
        "source": p.get("source"),
        "primary": p.get("primary"),
        "secondary": p.get("secondary"),
        "tertiary": p.get("tertiary"),
        "identity": identity,
        "credits": p.get("credits_remaining"),
        "updated_at": p.get("updated_at"),
        "pace_summary": p.get("pace_summary"),
        "headline_remaining": p.get("headline_remaining"),
    }
    if err:
        snap["error"] = err
    return snap


def _views_to_aipc_usage_list() -> list:
    """Hermes / aipc-usage compatible GET /usage body: list[{provider, snapshot}]."""
    data = _views_to_json()
    rows = []
    for p in data.get("providers") or []:
        if not isinstance(p, dict):
            continue
        pid = p.get("provider") or "unknown"
        rows.append({"provider": pid, "snapshot": _provider_to_aipc_snapshot(p)})
    return rows


class _Handler(BaseHTTPRequestHandler):
    server_version = "codexbar-gui-web/0.5"

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
        # aipc-usage / Hermes quota MCP drop-in (replaces :8080 JSON)
        if path == "/usage":
            try:
                payload = _views_to_aipc_usage_list()
            except Exception as exc:
                payload = [
                    {
                        "provider": "error",
                        "snapshot": {
                            "provider": "error",
                            "status": "error",
                            "error": str(exc),
                            "primary": None,
                            "secondary": None,
                            "identity": {},
                        },
                    }
                ]
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(200, raw, "application/json; charset=utf-8")
            return
        if path == "/health":
            raw = json.dumps(
                {
                    "status": "ok",
                    "role": "codexbar-gui-web",
                    "version": "0.5.0",
                    "binary": find_codexbar_binary(),
                    "endpoints": ["/", "/api/usage", "/usage", "/health"],
                }
            ).encode()
            self._send(200, raw, "application/json; charset=utf-8")
            return
        self._send(
            404,
            json.dumps(
                {
                    "error": "not found",
                    "hint": "GET / | /api/usage | /usage | /health",
                }
            ).encode(),
            "application/json; charset=utf-8",
        )


_httpd: Optional[ThreadingHTTPServer] = None
_thread: Optional[threading.Thread] = None


def _probe_our_web(host: str, port: int) -> Optional[str]:
    """If host:port already serves this webapp, return its URL."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=1.5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        conn.close()
        if resp.status != 200:
            return None
        data = json.loads(body)
        if isinstance(data, dict) and data.get("role") == "codexbar-gui-web":
            return f"http://{host}:{port}/"
        # Accept healthy generic status only if /usage also lists providers.
        if isinstance(data, dict) and data.get("status") == "ok":
            conn2 = http.client.HTTPConnection(host, port, timeout=1.5)
            conn2.request("GET", "/usage")
            r2 = conn2.getresponse()
            b2 = r2.read()
            conn2.close()
            if r2.status == 200:
                rows = json.loads(b2.decode("utf-8", errors="replace"))
                if isinstance(rows, list):
                    return f"http://{host}:{port}/"
    except Exception:
        return None
    return None


def start_web(
    host: str = DEFAULT_WEB_HOST,
    port: int = DEFAULT_WEB_PORT,
) -> tuple[bool, str]:
    """Start background web UI. Returns (ok, url_or_error).

    If ``port`` is already owned by this app (e.g. systemd ``codexbar-gui-web``),
    reuse it instead of binding a second listener.
    """
    global _httpd, _thread
    if _httpd is not None:
        return True, f"http://{host}:{_httpd.server_address[1]}/"

    existing = _probe_our_web(host, port)
    if existing:
        logger.info("web UI already up: %s", existing)
        return True, existing

    try:
        httpd = ThreadingHTTPServer((host, port), _Handler)
    except OSError as exc:
        # Prefer reusing our own service over hopping to a random alt port.
        existing = _probe_our_web(host, port)
        if existing:
            logger.info("bind failed; reusing existing web UI: %s", existing)
            return True, existing
        for alt in (8787, port + 1, port + 2, 8790, 8791):
            if alt == port:
                continue
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
    httpd = _httpd
    _httpd = None
    if httpd is not None:
        try:
            httpd.shutdown()
        except Exception:
            logger.debug("httpd.shutdown", exc_info=True)
        try:
            httpd.server_close()
        except Exception:
            logger.debug("httpd.server_close", exc_info=True)
    thr = _thread
    _thread = None
    if thr is not None and thr.is_alive():
        thr.join(timeout=2.0)


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
