"""Official CodexBar CLI / serve adapter (core logic stays upstream).

Scope of this repo's GUI module: **display only**.
All quotas/OAuth/provider fetch live in the official Linux ``codexbar`` binary
(https://github.com/steipete/CodexBar). We only parse its JSON.

Fetch order:
1. HTTP ``GET /usage`` if ``codexbar serve`` is already up
2. Subprocess ``codexbar usage --format json``
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger("codexbar_gui.upstream")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
# Official CLI can hang when OAuth/network stalls; keep UI responsive.
CLI_TIMEOUT = float(os.environ.get("CODEXBAR_CLI_TIMEOUT", "35"))


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_resets_in(resets_at: Optional[str]) -> str:
    """Official-style countdown: ``Resets in 2h 24m`` / ``Resets in 7d``."""
    dt = _parse_iso(resets_at)
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((dt - now).total_seconds())
    if secs <= 0:
        return "Reset due"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days > 0:
        return f"Resets in {days}d {hours}h" if hours else f"Resets in {days}d"
    if hours > 0:
        return f"Resets in {hours}h {mins}m" if mins else f"Resets in {hours}h"
    return f"Resets in {mins}m"


def format_updated_ago(updated_at: Optional[str]) -> str:
    """``Updated just now`` / ``Updated 3m ago`` (official freshness line)."""
    dt = _parse_iso(updated_at)
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = max(0, int((now - dt).total_seconds()))
    if secs < 45:
        return "Updated just now"
    if secs < 3600:
        return f"Updated {secs // 60}m ago"
    if secs < 86400:
        return f"Updated {secs // 3600}h ago"
    return f"Updated {secs // 86400}d ago"


@dataclass
class RateWindowView:
    label: str
    used_percent: float  # 0–100 used
    remaining_percent: float  # 0–100 remaining (menu-bar default)
    reset_description: str = ""
    window_minutes: Optional[int] = None
    resets_at: Optional[str] = None

    @property
    def resets_in(self) -> str:
        return format_resets_in(self.resets_at) or (
            f"Resets {self.reset_description}" if self.reset_description else ""
        )


@dataclass
class ProviderView:
    provider: str
    source: str = ""
    error: Optional[str] = None
    account: Optional[str] = None
    plan: Optional[str] = None
    version: Optional[str] = None
    primary: Optional[RateWindowView] = None
    secondary: Optional[RateWindowView] = None
    tertiary: Optional[RateWindowView] = None
    pace_summary: Optional[str] = None
    credits_remaining: Optional[float] = None
    reset_credits_available: Optional[int] = None
    data_confidence: Optional[str] = None
    updated_at: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.provider.replace("_", " ").title()

    @property
    def plan_label(self) -> str:
        if not self.plan:
            return ""
        return self.plan.replace("_", " ").title()

    @property
    def updated_label(self) -> str:
        return format_updated_ago(self.updated_at)

    @property
    def headline_remaining(self) -> Optional[float]:
        """Menu-bar style: primary remaining %, else secondary."""
        if self.primary is not None:
            return self.primary.remaining_percent
        if self.secondary is not None:
            return self.secondary.remaining_percent
        return None

    @property
    def ok(self) -> bool:
        return self.error is None and (
            self.primary is not None or self.secondary is not None
        )


def find_codexbar_binary() -> Optional[str]:
    env = os.environ.get("CODEXBAR_BIN")
    if env and Path(env).is_file():
        return env
    which = shutil.which("codexbar")
    if which:
        return which
    for p in (
        Path.home() / ".local/bin/codexbar",
        Path.home() / ".local/opt/codexbar/CodexBarCLI",
        Path("/usr/bin/codexbar"),
    ):
        if p.is_file():
            return str(p)
    return None


def _window_from_dict(label: str, data: Optional[dict]) -> Optional[RateWindowView]:
    if not isinstance(data, dict):
        return None
    # Official usedPercent is 0–100 (e.g. 1 = 1% used). Legacy aipc port may
    # emit a 0–1 fraction; only scale true open-unit fractions, never 1 or 2.
    raw = data.get("usedPercent", data.get("used_percent"))
    if raw is None:
        return None
    try:
        used = float(raw)
    except (TypeError, ValueError):
        return None
    if 0.0 < used < 1.0:
        used *= 100.0
    used = max(0.0, min(100.0, used))
    mins = data.get("windowMinutes", data.get("window_minutes"))
    try:
        mins_i = int(mins) if mins is not None else None
    except (TypeError, ValueError):
        mins_i = None
    label_map = {
        300: "Session (5h)",
        10080: "Weekly",
    }
    if mins_i in label_map:
        label = label_map[mins_i]
    return RateWindowView(
        label=label,
        used_percent=used,
        remaining_percent=max(0.0, 100.0 - used),
        reset_description=str(
            data.get("resetDescription") or data.get("reset_description") or ""
        ),
        window_minutes=mins_i,
        resets_at=data.get("resetsAt") or data.get("resets_at"),
    )


def parse_upstream_item(item: dict[str, Any]) -> ProviderView:
    """Normalize one official ``codexbar usage --format json`` object."""
    provider = str(item.get("provider") or "unknown")
    err = item.get("error")
    err_msg = None
    if isinstance(err, dict):
        err_msg = str(err.get("message") or err)
    elif isinstance(err, str):
        err_msg = err

    usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
    # aipc-usage port wraps as {provider, snapshot: {...}}
    if not usage and isinstance(item.get("snapshot"), dict):
        snap = item["snapshot"]
        if snap.get("primary") or snap.get("secondary") or snap.get("status"):
            return _parse_port_snapshot(provider, snap, item)

    pace = item.get("pace") if isinstance(item.get("pace"), dict) else {}
    pace_primary = pace.get("primary") if isinstance(pace.get("primary"), dict) else {}
    credits = item.get("credits") if isinstance(item.get("credits"), dict) else {}
    identity = usage.get("identity") if isinstance(usage.get("identity"), dict) else {}
    reset_creds = (
        usage.get("codexResetCredits")
        if isinstance(usage.get("codexResetCredits"), dict)
        else {}
    )

    account = (
        item.get("account")
        or usage.get("accountEmail")
        or identity.get("accountEmail")
    )
    plan = usage.get("loginMethod") or identity.get("loginMethod")
    creds = credits.get("remaining")
    try:
        creds_f = float(creds) if creds is not None else None
    except (TypeError, ValueError):
        creds_f = None
    try:
        reset_n = (
            int(reset_creds["availableCount"])
            if reset_creds.get("availableCount") is not None
            else None
        )
    except (TypeError, ValueError):
        reset_n = None

    updated = (
        usage.get("updatedAt")
        or credits.get("updatedAt")
        or item.get("updatedAt")
    )

    return ProviderView(
        provider=provider,
        source=str(item.get("source") or ""),
        error=err_msg,
        account=str(account) if account else None,
        plan=str(plan) if plan else None,
        version=str(item.get("version") or "") or None,
        primary=_window_from_dict("Session", usage.get("primary")),
        secondary=_window_from_dict("Weekly", usage.get("secondary")),
        tertiary=_window_from_dict("Extra", usage.get("tertiary")),
        pace_summary=(
            str(pace_primary.get("summary")) if pace_primary.get("summary") else None
        ),
        credits_remaining=creds_f,
        reset_credits_available=reset_n,
        data_confidence=str(usage.get("dataConfidence") or "") or None,
        updated_at=str(updated) if updated else None,
        raw=item,
    )


def _parse_port_snapshot(
    provider: str, snap: dict[str, Any], item: dict[str, Any]
) -> ProviderView:
    """Legacy aipc-usage shape (mostly useless; kept as last-resort)."""
    status = snap.get("status") or ""
    err = snap.get("error")
    if status in {"no-api-key", "not-configured", "not-implemented"} and not err:
        err = status
    return ProviderView(
        provider=provider,
        source="aipc-usage-port",
        error=str(err) if err else (None if status == "ok" else status or "unknown"),
        account=(snap.get("identity") or {}).get("account_email")
        if isinstance(snap.get("identity"), dict)
        else None,
        primary=_window_from_dict("Primary", snap.get("primary")),
        secondary=_window_from_dict("Secondary", snap.get("secondary")),
        raw=item,
    )


def parse_upstream_list(data: Any) -> List[ProviderView]:
    if not isinstance(data, list):
        return []
    return [parse_upstream_item(x) for x in data if isinstance(x, dict)]


def fetch_from_http(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    provider: Optional[str] = None,
    timeout: float = 8.0,
) -> Optional[List[ProviderView]]:
    path = "/usage"
    if provider:
        path += f"?provider={provider}"
    url = f"http://{host}:{port}{path}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as exc:
        logger.debug("HTTP usage failed: %s", exc)
        return None
    return parse_upstream_list(body)


def _cli_provider_arg(provider: Optional[str]) -> Optional[str]:
    """Which ``--provider`` to pass.

    Bare ``codexbar usage`` (all enabled providers) can hang for minutes when a
    secondary provider (e.g. Claude cookie scrape) stalls — leaving tray/web
    empty. Default to **codex** only; override with ``CODEXBAR_PROVIDER`` or
    set ``CODEXBAR_ALL_PROVIDERS=1`` for the full list.
    """
    if provider:
        return provider
    env = (os.environ.get("CODEXBAR_PROVIDER") or "").strip()
    if env:
        return env
    if os.environ.get("CODEXBAR_ALL_PROVIDERS", "").lower() in {"1", "true", "yes"}:
        return None
    return "codex"


def fetch_from_cli(
    provider: Optional[str] = None,
    timeout: float = CLI_TIMEOUT,
) -> Optional[List[ProviderView]]:
    binary = find_codexbar_binary()
    if not binary:
        return None
    # Cap upstream web scrape so one slow provider cannot hang forever.
    web_to = max(5, min(int(timeout), 60))
    cmd = [
        binary,
        "usage",
        "--format",
        "json",
        "--web-timeout",
        str(web_to),
    ]
    prov = _cli_provider_arg(provider)
    if prov:
        cmd.extend(["--provider", prov])
    logger.info("CLI: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("codexbar CLI failed: %s", exc)
        return None
    # JSON may be on stdout even when exit != 0 (partial providers).
    text = (proc.stdout or "").strip()
    if not text:
        logger.warning("codexbar CLI empty stdout: %s", (proc.stderr or "")[:200])
        return None
    # Some builds mix logs — find first '['
    start = text.find("[")
    if start < 0:
        return None
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError:
        return None
    return parse_upstream_list(data)


def fetch_usage_views(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    prefer_cli: bool = True,
) -> List[ProviderView]:
    """Fetch from official codexbar only.

    Default **prefer_cli=True**: always call ``codexbar usage --format json``
    so a stale Python server on :8080 cannot poison the tray. HTTP is only
    used when it is verified official serve *and* prefer_cli is False.
    """
    if not find_codexbar_binary():
        logger.error("codexbar binary not found — install official Linux CLI")
        return []

    if not prefer_cli and is_official_serve(host, port):
        http = fetch_from_http(host, port)
        if http is not None:
            return http

    cli = fetch_from_cli()
    if cli is not None:
        return cli

    if is_official_serve(host, port):
        return fetch_from_http(host, port) or []
    return []


def health_check(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """True only if an *official* codexbar serve is healthy.

    The broken Python ``aipc-usage`` / ``codexbar_usage`` port also answers
    ``/health`` with ``status=ok`` and ``version=0.1.0`` on :8080 — that must
    not be treated as success (it returns fake no-api-key usage).
    """
    return is_official_serve(host, port)


def is_official_serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    try:
        req = urllib.request.Request(f"http://{host}:{port}/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            health = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    if health.get("status") != "ok":
        return False
    ver = str(health.get("version") or "")
    # Python port ships 0.1.0; official CLI is 0.40.x etc.
    if ver in {"0.1.0", "0.1", "aipc"} or ver.startswith("0.1."):
        logger.warning(
            "port %s looks like aipc-usage Python port (version=%s), not official codexbar",
            port,
            ver,
        )
        return False

    # Probe usage shape: official items use top-level "usage" / "source"
    try:
        req = urllib.request.Request(f"http://{host}:{port}/usage", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("usage probe failed on :%s: %s", port, exc)
        # Without a version we refuse to trust health-only.
        return bool(ver) and not ver.startswith("0.1")
    if not isinstance(body, list) or not body:
        return bool(ver) and not ver.startswith("0.1")
    sample = body[0] if isinstance(body[0], dict) else {}
    if "snapshot" in sample and "usage" not in sample:
        logger.warning("port %s returns aipc-usage snapshot shape — ignoring", port)
        return False
    # Official items typically have "usage" and/or "source" / "pace"
    if "usage" in sample or "source" in sample or "pace" in sample:
        return True
    if "error" in sample and "provider" in sample:
        return True
    return False
