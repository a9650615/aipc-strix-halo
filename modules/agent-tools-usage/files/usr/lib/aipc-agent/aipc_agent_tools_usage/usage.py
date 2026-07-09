"""Usage tools for the local aipc assistant.

Source of truth: official Linux ``codexbar`` CLI JSON (same as macOS app),
not the incomplete Python port.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any, Optional

TIMEOUT = float(os.environ.get("AIPC_USAGE_TIMEOUT", "90"))
USAGE_ENDPOINT = os.environ.get("AIPC_USAGE_ENDPOINT", "http://127.0.0.1:8080").rstrip(
    "/"
)


def available_tools() -> list[str]:
    tools = ["usage.lookup"]
    if _find_codexbar() or _http_health():
        tools.append("usage.lookup.live")
    return tools


def lookup_usage(providers: Optional[str] = None) -> dict[str, Any]:
    ids = _parse_ids(providers)

    for fetcher in (_from_official_cli, _from_http):
        try:
            raw = fetcher(ids)
        except Exception:
            continue
        if raw is None:
            continue
        return _normalize_upstream(raw, ids)

    return {
        "status": "not_configured",
        "tool": "usage.lookup",
        "providers": [],
        "detail": (
            "Install official CodexBar Linux CLI (codexbar) or run "
            "`codexbar serve`. See https://github.com/steipete/CodexBar/releases"
        ),
    }


def _parse_ids(providers: Optional[str]) -> Optional[list[str]]:
    if not providers:
        return None
    if isinstance(providers, (list, tuple)):
        return [str(p).strip() for p in providers if str(p).strip()]
    parts = [p.strip() for p in str(providers).split(",") if p.strip()]
    return parts or None


def _find_codexbar() -> Optional[str]:
    env = os.environ.get("CODEXBAR_BIN")
    if env and os.path.isfile(env):
        return env
    which = shutil.which("codexbar")
    if which:
        return which
    home = os.path.expanduser("~")
    for p in (
        f"{home}/.local/bin/codexbar",
        f"{home}/.local/opt/codexbar/CodexBarCLI",
        "/usr/bin/codexbar",
    ):
        if os.path.isfile(p):
            return p
    return None


def _http_health() -> bool:
    try:
        req = urllib.request.Request(USAGE_ENDPOINT + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode()).get("status") == "ok"
    except Exception:
        return False


def _from_official_cli(ids: Optional[list[str]]) -> Optional[list]:
    binary = _find_codexbar()
    if not binary:
        return None
    cmd = [binary, "usage", "--format", "json"]
    if ids and len(ids) == 1:
        cmd.extend(["--provider", ids[0]])
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False
    )
    text = (proc.stdout or "").strip()
    if not text:
        return None
    start = text.find("[")
    if start < 0:
        return None
    data = json.loads(text[start:])
    if ids and len(ids) > 1:
        want = set(ids)
        data = [x for x in data if isinstance(x, dict) and x.get("provider") in want]
    return data if isinstance(data, list) else None


def _from_http(ids: Optional[list[str]]) -> Optional[list]:
    url = USAGE_ENDPOINT + "/usage"
    if ids and len(ids) == 1:
        url += f"?provider={ids[0]}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=min(TIMEOUT, 30)) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    if ids and len(ids) > 1:
        want = set(ids)
        data = [x for x in data if isinstance(x, dict) and x.get("provider") in want]
    return data


def _used_pct(window: Optional[dict]) -> Optional[float]:
    if not isinstance(window, dict):
        return None
    raw = window.get("usedPercent", window.get("used_percent"))
    if raw is None:
        return None
    val = float(raw)
    if 0.0 <= val <= 2.0:
        val *= 100.0
    return max(0.0, min(100.0, val))


def _normalize_upstream(raw: list, ids: Optional[list[str]]) -> dict[str, Any]:
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("provider") or "unknown")
        if ids and pid not in ids:
            continue
        err = item.get("error")
        err_msg = None
        if isinstance(err, dict):
            err_msg = str(err.get("message") or err)
        elif isinstance(err, str):
            err_msg = err

        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        # legacy aipc port wrapper
        if not usage and isinstance(item.get("snapshot"), dict):
            snap = item["snapshot"]
            primary = snap.get("primary") or {}
            out.append(
                {
                    "id": pid,
                    "name": pid,
                    "status": snap.get("status") or ("error" if snap.get("error") else "ok"),
                    "used_percent": _used_pct(primary),
                    "remaining_percent": (
                        None
                        if _used_pct(primary) is None
                        else 100.0 - float(_used_pct(primary))
                    ),
                    "reset": primary.get("reset_description"),
                    "detail": snap.get("error"),
                }
            )
            continue

        primary = usage.get("primary") if isinstance(usage.get("primary"), dict) else {}
        secondary = (
            usage.get("secondary") if isinstance(usage.get("secondary"), dict) else {}
        )
        pace = item.get("pace") if isinstance(item.get("pace"), dict) else {}
        pace_p = pace.get("primary") if isinstance(pace.get("primary"), dict) else {}
        identity = (
            usage.get("identity") if isinstance(usage.get("identity"), dict) else {}
        )
        used = _used_pct(primary)
        rem = None if used is None else 100.0 - used
        week_used = _used_pct(secondary)
        out.append(
            {
                "id": pid,
                "name": pid,
                "status": "error" if err_msg else "ok",
                "used_percent": used,
                "remaining_percent": rem,
                "session_remaining_percent": rem,
                "weekly_used_percent": week_used,
                "weekly_remaining_percent": (
                    None if week_used is None else 100.0 - week_used
                ),
                "reset": primary.get("resetDescription")
                or primary.get("reset_description"),
                "weekly_reset": secondary.get("resetDescription")
                or secondary.get("reset_description"),
                "pace": pace_p.get("summary"),
                "account": item.get("account")
                or usage.get("accountEmail")
                or identity.get("accountEmail"),
                "plan": usage.get("loginMethod") or identity.get("loginMethod"),
                "source": item.get("source"),
                "detail": err_msg,
            }
        )

    overall = "ok" if out else "error"
    if out and all(p.get("status") == "error" for p in out):
        overall = "error"
    return {"status": overall, "tool": "usage.lookup", "providers": out}


def self_test() -> None:
    # Shape test with synthetic official payload
    raw = [
        {
            "provider": "codex",
            "source": "oauth",
            "usage": {
                "primary": {
                    "usedPercent": 32,
                    "resetDescription": "in 3m",
                    "windowMinutes": 300,
                },
                "secondary": {
                    "usedPercent": 100,
                    "resetDescription": "Jul 13",
                    "windowMinutes": 10080,
                },
                "accountEmail": "x@y.z",
                "loginMethod": "plus",
            },
            "pace": {"primary": {"summary": "67% in reserve"}},
        }
    ]
    norm = _normalize_upstream(raw, None)
    assert norm["status"] == "ok"
    p = norm["providers"][0]
    assert p["used_percent"] == 32
    assert p["remaining_percent"] == 68
    assert p["weekly_used_percent"] == 100
    assert p["account"] == "x@y.z"
    empty = lookup_usage("__no_such_xyz__")
    assert empty["tool"] == "usage.lookup"
    print("aipc_agent_tools_usage self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
    else:
        print(json.dumps(lookup_usage(), indent=2, ensure_ascii=False))
