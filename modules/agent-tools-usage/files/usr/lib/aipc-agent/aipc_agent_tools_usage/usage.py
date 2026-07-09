"""Usage tools for the local aipc assistant (Daily Assistant / LangGraph).

Thin, fail-soft lookups of AI coding provider quotas. Perfect CodexBar port
is not the goal — the assistant needs a callable that returns a stable dict.

Resolution order for ``lookup_usage``:
1. In-process ``codexbar_usage.fetch`` (module installed in image / venv)
2. Local HTTP ``GET {AIPC_USAGE_ENDPOINT}/usage`` (GUI/serve already up)
3. Subprocess ``aipc-usage usage -f json`` if on PATH
4. ``{"status": "not_configured"}``

Never raises out to the graph.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

TIMEOUT = float(os.environ.get("AIPC_USAGE_TIMEOUT", "8.0"))
USAGE_ENDPOINT = os.environ.get(
    "AIPC_USAGE_ENDPOINT", "http://127.0.0.1:8080"
).rstrip("/")


def available_tools() -> list[str]:
    """Advertise tools the assistant can bind — always include lookup."""
    tools = ["usage.lookup"]
    if _codexbar_importable() or shutil.which("aipc-usage") or _http_health():
        tools.append("usage.lookup.live")
    return tools


def lookup_usage(providers: Optional[str] = None) -> dict[str, Any]:
    """Return structured usage for one or more providers.

    Args:
        providers: Comma-separated provider ids (e.g. ``claude,openai``).
            Empty / None = whatever the backend's default set is.

    Returns:
        ``{"status": "ok"|"error"|"not_configured", "tool": "usage.lookup",
          "providers": [{id, name, status, used_percent, reset, detail}, ...]}``
    """
    ids = _parse_ids(providers)

    for fetcher in (_from_codexbar_fetch, _from_http, _from_cli):
        try:
            raw = fetcher(ids)
        except Exception:  # noqa: BLE001 — fail soft for the agent
            continue
        if raw is None:
            continue
        if isinstance(raw, dict) and raw.get("status") == "error":
            continue
        return _normalize(raw, ids)

    # Nothing worked.
    return {
        "status": "not_configured",
        "tool": "usage.lookup",
        "providers": [],
        "detail": (
            "No usage backend available. Install modules/dev-ai-codexbar-usage "
            "or run `aipc usage serve` / enable aipc-usage.service."
        ),
    }


def _parse_ids(providers: Optional[str]) -> Optional[list[str]]:
    if not providers:
        return None
    if isinstance(providers, (list, tuple)):
        return [str(p).strip() for p in providers if str(p).strip()]
    parts = [p.strip() for p in str(providers).split(",") if p.strip()]
    return parts or None


def _codexbar_importable() -> bool:
    try:
        import codexbar_usage  # noqa: F401

        return True
    except ImportError:
        pass

    candidates: list[str] = []
    env_pkg = os.environ.get("AIPC_CODEXBAR_USAGE_PKG")
    if env_pkg:
        candidates.append(env_pkg)
    candidates.append("/usr/lib/aipc-codexbar-usage")
    # Walk up from this file to find modules/dev-ai-codexbar-usage (dev tree).
    here = os.path.abspath(os.path.dirname(__file__))
    cur = here
    for _ in range(10):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        if os.path.basename(cur) == "modules":
            candidates.append(
                os.path.join(
                    cur,
                    "dev-ai-codexbar-usage",
                    "files",
                    "usr",
                    "lib",
                    "aipc-codexbar-usage",
                )
            )
            break
        cur = parent

    for c in candidates:
        c = os.path.abspath(c)
        if not os.path.isdir(c):
            continue
        if c not in sys.path:
            sys.path.insert(0, c)
        try:
            import codexbar_usage  # noqa: F401

            return True
        except ImportError:
            continue
    return False


def _from_codexbar_fetch(ids: Optional[list[str]]) -> Optional[list[dict]]:
    if not _codexbar_importable():
        return None
    from codexbar_usage.fetch import fetch_all_usage

    return fetch_all_usage(providers=ids)


def _http_health() -> bool:
    try:
        req = urllib.request.Request(USAGE_ENDPOINT + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _from_http(ids: Optional[list[str]]) -> Optional[list[dict]]:
    url = USAGE_ENDPOINT + "/usage"
    if ids:
        url += "?" + urllib.parse.urlencode({"provider": ids[0]})
        # Multi-provider: fetch all and filter client-side (server filter is single).
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    if ids and len(ids) > 1:
        want = set(ids)
        data = [row for row in data if row.get("provider") in want]
    return data


def _from_cli(ids: Optional[list[str]]) -> Optional[list[dict]]:
    bin_path = shutil.which("aipc-usage")
    if not bin_path:
        return None
    cmd = [bin_path, "usage", "-f", "json"]
    if ids:
        cmd.extend(["-p", ",".join(ids)])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT + 5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "rows" in data:
        return data["rows"]
    return None


def _normalize(raw: list[dict] | dict, ids: Optional[list[str]]) -> dict[str, Any]:
    if isinstance(raw, dict) and "providers" in raw:
        return raw

    rows = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = row.get("provider") or row.get("id") or "unknown"
        snap = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else row
        primary = snap.get("primary") if isinstance(snap.get("primary"), dict) else {}
        used = primary.get("used_percent")
        # Accept 0–1 fraction or 0–100 percent.
        if used is not None:
            try:
                used_f = float(used)
                if 0.0 <= used_f <= 2.0:
                    used_f = round(used_f * 100.0, 1)
                else:
                    used_f = round(used_f, 1)
            except (TypeError, ValueError):
                used_f = None
        else:
            used_f = None
        out.append(
            {
                "id": pid,
                "name": snap.get("display_name") or row.get("display_name") or pid,
                "status": snap.get("status") or row.get("status") or "unknown",
                "used_percent": used_f,
                "reset": primary.get("reset_description"),
                "detail": snap.get("error") or row.get("error"),
            }
        )

    if ids:
        want = set(ids)
        out = [p for p in out if p["id"] in want]

    overall = "ok"
    if not out:
        overall = "error"
    elif all(p.get("status") in {"no-api-key", "not-configured", "not-implemented"} for p in out):
        overall = "ok"  # still useful info for the assistant
    return {
        "status": overall,
        "tool": "usage.lookup",
        "providers": out,
    }


def self_test() -> None:
    """No network required for shape checks; network paths fail soft."""
    empty = lookup_usage("__no_such_provider_xyz__")
    assert empty["tool"] == "usage.lookup"
    assert empty["status"] in {"ok", "error", "not_configured"}
    assert isinstance(empty.get("providers"), list)

    # Normalize path unit test
    fake = [
        {
            "provider": "claude",
            "snapshot": {
                "display_name": "Claude",
                "status": "ok",
                "primary": {
                    "used_percent": 0.42,
                    "reset_description": "in 3h",
                },
            },
        }
    ]
    norm = _normalize(fake, ["claude"])
    assert norm["status"] == "ok"
    assert norm["providers"][0]["used_percent"] == 42.0
    assert norm["providers"][0]["reset"] == "in 3h"

    assert "usage.lookup" in available_tools()
    print("aipc_agent_tools_usage self_test: OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(json.dumps(lookup_usage(), indent=2, ensure_ascii=False))
