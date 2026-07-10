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
import re
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
class PaceInfo:
    """Burn-rate vs linear schedule until reset (official reserve/deficit).

    positive reserve_percent → under budget (slower than expected)
    negative → over pace (faster than expected)
    """

    reserve_percent: float  # expected_used - actual_used
    expected_used_percent: float
    will_last_to_reset: bool
    summary: str
    source: str = "computed"  # or "cli"

    @property
    def status(self) -> str:
        if abs(self.reserve_percent) < 2.0:
            return "on_pace"
        return "reserve" if self.reserve_percent > 0 else "deficit"


def compute_pace(
    used_percent: float,
    window_minutes: Optional[int],
    resets_at: Optional[str],
) -> Optional[PaceInfo]:
    """Compare actual used% to linear burn across the rate window.

    Official CodexBar: ``13% in reserve`` / ``Lasts until reset`` when you are
    under the straight-line schedule; opposite when burning faster.
    """
    if window_minutes is None or window_minutes <= 0:
        return None
    dt = _parse_iso(resets_at)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs_left = (dt - now).total_seconds()
    window_secs = float(window_minutes) * 60.0
    # Clamp: if reset is far beyond window length, treat remaining as full window
    secs_left = max(0.0, min(window_secs, secs_left))
    elapsed_frac = 1.0 - (secs_left / window_secs)
    expected_used = max(0.0, min(100.0, elapsed_frac * 100.0))
    actual = max(0.0, min(100.0, used_percent))
    reserve = expected_used - actual  # + = under budget
    will_last = actual <= expected_used + 0.5  # tiny slack

    if reserve >= 2.0:
        summary = f"{int(round(reserve))}% in reserve · Lasts until reset"
    elif reserve <= -2.0:
        over = -reserve
        # Rough time-to-exhaustion at current average burn rate
        if actual > 0.5 and elapsed_frac > 0.01:
            burn_per_sec = actual / (elapsed_frac * window_secs)
            secs_to_empty = (100.0 - actual) / burn_per_sec if burn_per_sec > 0 else 0
            if secs_to_empty < secs_left and secs_to_empty > 0:
                h = int(secs_to_empty // 3600)
                m = int((secs_to_empty % 3600) // 60)
                if h > 0:
                    eta = f"{h}h {m}m" if m else f"{h}h"
                else:
                    eta = f"{m}m"
                summary = f"{int(round(over))}% over pace · May run out in ~{eta}"
            else:
                summary = f"{int(round(over))}% over pace · Faster than expected"
        else:
            summary = f"{int(round(over))}% over pace · Faster than expected"
    else:
        summary = "On pace · Lasts until reset"

    return PaceInfo(
        reserve_percent=reserve,
        expected_used_percent=expected_used,
        will_last_to_reset=will_last,
        summary=summary,
        source="computed",
    )


def _pace_from_cli(pace_blob: Optional[dict]) -> Optional[PaceInfo]:
    if not isinstance(pace_blob, dict):
        return None
    summary = pace_blob.get("summary")
    if not summary:
        return None
    try:
        delta = float(pace_blob.get("deltaPercent"))
    except (TypeError, ValueError):
        # e.g. "67% in reserve" without delta
        delta = 0.0
        low = str(summary).lower()
        if "reserve" in low:
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", str(summary))
            if m:
                # "67% in reserve" → +67 reserve; official delta was often negative
                delta = abs(float(m.group(1)))
        if "over" in low or "deficit" in low or "ahead" in low:
            delta = -abs(delta) if delta else -1.0
    will = pace_blob.get("willLastToReset")
    if will is None:
        will = delta >= 0
    try:
        expected = float(pace_blob.get("expectedUsedPercent", 0.0))
    except (TypeError, ValueError):
        expected = 0.0
    # Official deltaPercent often means "ahead of schedule" as negative
    # (e.g. -67 → 67% in reserve). Prefer summary keywords.
    low = str(summary).lower()
    if "reserve" in low and delta < 0:
        reserve = -delta
    elif "reserve" in low:
        reserve = abs(delta)
    elif delta != 0:
        reserve = -delta  # negative delta → reserve in some builds
    else:
        reserve = 0.0
    return PaceInfo(
        reserve_percent=reserve,
        expected_used_percent=expected,
        will_last_to_reset=bool(will),
        summary=str(summary),
        source="cli",
    )


@dataclass
class RateWindowView:
    label: str
    used_percent: float  # 0–100 used
    remaining_percent: float  # 0–100 remaining (menu-bar default)
    reset_description: str = ""
    window_minutes: Optional[int] = None
    resets_at: Optional[str] = None
    pace: Optional[PaceInfo] = None

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
    extra_windows: List[RateWindowView] = field(default_factory=list)
    pace_summary: Optional[str] = None
    credits_remaining: Optional[float] = None
    reset_credits_available: Optional[int] = None
    data_confidence: Optional[str] = None
    updated_at: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def all_windows(self) -> List[RateWindowView]:
        out: List[RateWindowView] = []
        for w in (self.primary, self.secondary, self.tertiary):
            if w is not None:
                out.append(w)
        out.extend(self.extra_windows)
        return out

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
            self.primary is not None
            or self.secondary is not None
            or bool(self.extra_windows)
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


def _window_from_dict(
    label: str,
    data: Optional[dict],
    *,
    cli_pace: Optional[dict] = None,
) -> Optional[RateWindowView]:
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
    # Prefer explicit title from extra windows
    title = (
        data.get("title")
        or data.get("name")
        or data.get("id")
    )
    label_map = {
        300: "Session",
        10080: "Weekly",
    }
    if title:
        label = str(title).replace("_", " ").replace("-", " ").title()
    elif mins_i in label_map and label in {
        "Session",
        "Weekly",
        "Extra",
        "Primary",
        "Secondary",
    }:
        # Only rename primary lanes — do not clobber Designs / Daily Routines etc.
        label = label_map[mins_i]
    resets_at = data.get("resetsAt") or data.get("resets_at")
    pace = _pace_from_cli(cli_pace) or compute_pace(used, mins_i, resets_at)
    return RateWindowView(
        label=label,
        used_percent=used,
        remaining_percent=max(0.0, 100.0 - used),
        reset_description=str(
            data.get("resetDescription") or data.get("reset_description") or ""
        ),
        window_minutes=mins_i,
        resets_at=resets_at,
        pace=pace,
    )


def _extra_windows_from_usage(usage: dict[str, Any]) -> List[RateWindowView]:
    """Official extraRateWindows / additional limits (Designs, Daily Routines…)."""
    raw = (
        usage.get("extraRateWindows")
        or usage.get("extra_rate_windows")
        or usage.get("additionalRateLimits")
        or usage.get("additional_rate_limits")
        or []
    )
    out: List[RateWindowView] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        # Shape: {id, title, window: {usedPercent,...}} or flat window
        win_data = item.get("window") if isinstance(item.get("window"), dict) else item
        label = str(
            item.get("title")
            or item.get("name")
            or item.get("id")
            or "Extra"
        )
        w = _window_from_dict(label, win_data)
        if w is not None:
            out.append(w)
    return out


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
    pace_secondary = (
        pace.get("secondary") if isinstance(pace.get("secondary"), dict) else {}
    )
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

    primary = _window_from_dict(
        "Session", usage.get("primary"), cli_pace=pace_primary or None
    )
    secondary = _window_from_dict(
        "Weekly", usage.get("secondary"), cli_pace=pace_secondary or None
    )
    tertiary = _window_from_dict("Extra", usage.get("tertiary"))
    extras = _extra_windows_from_usage(usage)

    # Prefer weekly pace for card-level summary (official menu highlights weekly reserve)
    card_pace = None
    if secondary and secondary.pace:
        card_pace = secondary.pace.summary
    elif primary and primary.pace:
        card_pace = primary.pace.summary
    elif pace_primary.get("summary"):
        card_pace = str(pace_primary.get("summary"))

    return ProviderView(
        provider=provider,
        source=str(item.get("source") or ""),
        error=err_msg,
        account=str(account) if account else None,
        plan=str(plan) if plan else None,
        version=str(item.get("version") or "") or None,
        primary=primary,
        secondary=secondary,
        tertiary=tertiary,
        extra_windows=extras,
        pace_summary=card_pace,
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


def enabled_providers_from_config() -> List[str]:
    """Enabled provider ids from official config (for multi-tab UI)."""
    for path in (
        Path.home() / ".config" / "codexbar" / "config.json",
        Path.home() / ".codexbar" / "config.json",
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out: List[str] = []
        for p in data.get("providers") or []:
            if isinstance(p, dict) and p.get("enabled") and p.get("id"):
                out.append(str(p["id"]))
        if out:
            return out
    return ["codex"]


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


def fetch_enabled_providers(
    providers: Optional[List[str]] = None,
    timeout: float = CLI_TIMEOUT,
) -> List[ProviderView]:
    """Fetch each enabled provider separately (avoids multi-provider hang)."""
    ids = providers or enabled_providers_from_config()
    # Cap concurrent-feeling sequential fetches
    max_n = int(os.environ.get("CODEXBAR_MAX_PROVIDERS", "8"))
    ids = ids[: max(1, max_n)]
    views: List[ProviderView] = []
    for pid in ids:
        try:
            batch = fetch_from_cli(provider=pid, timeout=timeout)
        except Exception:
            logger.warning("fetch %s failed", pid, exc_info=True)
            batch = None
        if batch:
            views.extend(batch)
        else:
            views.append(
                ProviderView(
                    provider=pid,
                    error=(
                        f"No data for {pid}. Check Settings → Usage source, "
                        f"or run: codexbar usage --provider {pid} --format json"
                    ),
                )
            )
    return views


def _usage_source_for_provider(provider_id: Optional[str]) -> Optional[str]:
    """Read official config.json ``source`` (auto|oauth|cli|web|api)."""
    if not provider_id:
        return None
    for path in (
        Path.home() / ".config" / "codexbar" / "config.json",
        Path.home() / ".codexbar" / "config.json",
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for p in data.get("providers") or []:
            if not isinstance(p, dict):
                continue
            if str(p.get("id") or "").lower() != provider_id.lower():
                continue
            src = str(p.get("source") or "").lower().strip()
            if src in {"oauth", "cli", "web", "api", "auto"}:
                return src
    return None


def _source_attempts(provider: Optional[str], configured: Optional[str]) -> List[Optional[str]]:
    """Ordered --source tries.

    Claude:
      - auto → oauth, then cli (skip hanging web)
      - api alone often 401s on personal keys; still fall back to oauth/cli
    """
    pid = (provider or "").lower()
    if configured and configured != "auto":
        if pid == "claude" and configured == "api":
            # Fake/admin API keys fail with cost_report 401 — keep trying session sources
            return ["api", "oauth", "cli"]
        return [configured]
    if pid == "claude":
        return ["oauth", "cli"]
    if pid == "codex":
        return ["oauth", "cli", None]  # None = auto
    return [None]


def _is_hard_stop_error(msg: Optional[str]) -> bool:
    if not msg:
        return False
    m = msg.lower()
    return "rate limit" in m


def _is_auth_fallback_error(msg: Optional[str]) -> bool:
    """401 / invalid key — try next source instead of stopping."""
    if not msg:
        return False
    m = msg.lower()
    return (
        "401" in m
        or "unauthorized" in m
        or "invalid api" in m
        or "cost_report" in m
        or "authentication" in m
        or "not authenticated" in m
    )


def _friendly_claude_error(msg: Optional[str], source: Optional[str]) -> Optional[str]:
    if not msg:
        return msg
    m = msg.lower()
    if "401" in m or "cost_report" in m:
        return (
            "Claude Admin API key rejected (HTTP 401). "
            "Session quotas need OAuth/CLI — set Usage source to auto or oauth in Settings, "
            "and remove any test API key. Local cost history still works."
        )
    if "rate limit" in m:
        return msg  # already friendly from CLI
    if "subscription notice without session" in m or "without session quota" in m:
        return (
            "Claude CLI has no session quota right now (subscription notice only). "
            "Try `claude login`, or wait for OAuth rate limit to clear. "
            "Cost chart below still uses local logs."
        )
    if source:
        return f"{msg} (source={source})"
    return msg


def fetch_from_cli(
    provider: Optional[str] = None,
    timeout: float = CLI_TIMEOUT,
    source: Optional[str] = None,
) -> Optional[List[ProviderView]]:
    binary = find_codexbar_binary()
    if not binary:
        return None
    prov = _cli_provider_arg(provider)
    configured = source or (_usage_source_for_provider(prov) if prov else None)
    # Ignore obvious placeholder keys for Claude — they force broken api mode
    if (prov or "").lower() == "claude" and configured == "api":
        if _claude_has_placeholder_api_key():
            configured = "auto"
    attempts = _source_attempts(prov, configured)

    last: Optional[List[ProviderView]] = None
    for src in attempts:
        views = _run_usage_cli(
            binary,
            provider=prov,
            source=src,
            timeout=timeout,
        )
        if not views:
            continue
        # Friendly Claude messages
        if (prov or "").lower() == "claude":
            for v in views:
                if v.error:
                    v.error = _friendly_claude_error(v.error, src)
        last = views
        # Prefer a successful window
        if any(v.ok for v in views):
            return views
        errs = [v.error for v in views if v.error]
        if any(_is_hard_stop_error(e) for e in errs):
            return views
        # 401 / auth → try next source
        if any(_is_auth_fallback_error(e) for e in errs):
            continue
        # Other hard errors: still try next for Claude, stop for others
        if (prov or "").lower() != "claude":
            return views
    return last


def _claude_has_placeholder_api_key() -> bool:
    for path in (
        Path.home() / ".config" / "codexbar" / "config.json",
        Path.home() / ".codexbar" / "config.json",
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for p in data.get("providers") or []:
            if not isinstance(p, dict):
                continue
            if str(p.get("id") or "").lower() != "claude":
                continue
            key = str(p.get("api_key") or p.get("apiKey") or "")
            if not key:
                return False
            low = key.lower()
            return "test" in low or key.endswith("...") or len(key) < 20
    return False


def _run_usage_cli(
    binary: str,
    *,
    provider: Optional[str],
    source: Optional[str],
    timeout: float,
) -> Optional[List[ProviderView]]:
    web_to = max(5, min(int(timeout), 45))
    # Claude oauth is usually fast; keep web scrape short to avoid multi-minute hangs
    if (provider or "").lower() == "claude" and (source or "oauth") in {"oauth", "cli"}:
        web_to = min(web_to, 20)
    cmd = [
        binary,
        "usage",
        "--format",
        "json",
        "--web-timeout",
        str(web_to),
    ]
    if provider:
        cmd.extend(["--provider", provider])
    if source:
        cmd.extend(["--source", source])
    logger.info("CLI: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("codexbar CLI timed out: %s", " ".join(cmd))
        if provider:
            return [
                ProviderView(
                    provider=provider,
                    source=source or "auto",
                    error=(
                        f"Timed out after {int(timeout)}s"
                        + (f" (source={source})" if source else "")
                        + ". Try Settings → Usage source, or wait and Refresh."
                    ),
                )
            ]
        return None
    except OSError as exc:
        logger.warning("codexbar CLI failed: %s", exc)
        return None

    text = (proc.stdout or "").strip()
    if not text:
        err = (proc.stderr or "").strip()
        logger.warning("codexbar CLI empty stdout: %s", err[:200])
        if provider and err:
            return [ProviderView(provider=provider, source=source or "", error=err[:300])]
        return None
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
