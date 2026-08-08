"""Claude OAuth token bridge for the official ``codexbar`` CLI.

The CLI reads Claude session credentials from ``~/.claude/.credentials.json``
only (``CLAUDE_CONFIG_DIR`` does not redirect it). ``ccs`` keeps the live tokens
per instance in ``~/.ccs/instances/<name>/.credentials.json`` and leaves the
shared file blank, so ``--source oauth`` reports *"Claude OAuth access token
missing"* while Claude Code is in fact logged in.

We resolve the freshest credential file ourselves, refresh an expired access
token against the official endpoint (writing the rotated pair back so Claude
Code keeps working), and hand the token to the CLI via
``CODEXBAR_CLAUDE_OAUTH_TOKEN``.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("codexbar_gui.claude_oauth")

CLIENT_ID = (
    os.environ.get("CODEXBAR_CLAUDE_OAUTH_CLIENT_ID", "").strip()
    or "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
)
TOKEN_URL = (
    os.environ.get("CODEXBAR_CLAUDE_TOKEN_URL", "").strip()
    or "https://platform.claude.com/v1/oauth/token"
)
# Refresh a little early — the CLI call itself takes seconds.
EXPIRY_SKEW_MS = 120_000
# Don't hammer the endpoint when refresh keeps failing (offline, revoked token).
REFRESH_RETRY_S = 300.0

_last_refresh_fail = 0.0


@dataclass
class ClaudeCreds:
    path: Path
    access_token: str
    refresh_token: str
    expires_at: int  # epoch ms; 0 when unknown

    def expired(self, now_ms: int) -> bool:
        return self.expires_at <= 0 or self.expires_at - EXPIRY_SKEW_MS <= now_ms


def credential_paths() -> List[Path]:
    """Every place a Claude Code session may keep ``claudeAiOauth``."""
    home = Path.home()
    cands: List[Path] = []
    cfg = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    for part in cfg.split(":"):
        if part.strip():
            cands.append(Path(part.strip()).expanduser() / ".credentials.json")
    cands.append(home / ".claude" / ".credentials.json")
    instances = home / ".ccs" / "instances"
    cands.extend(sorted(instances.glob("*/.credentials.json")))
    cands.extend(sorted(instances.glob("*/.claude/.credentials.json")))

    out: List[Path] = []
    seen = set()
    for p in cands:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def read_credentials(path: Path) -> Optional[ClaudeCreds]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    block = data.get("claudeAiOauth")
    if not isinstance(block, dict):
        return None
    access = str(block.get("accessToken") or block.get("access_token") or "").strip()
    refresh = str(block.get("refreshToken") or block.get("refresh_token") or "").strip()
    if not access and not refresh:
        return None
    try:
        expires_at = int(block.get("expiresAt") or block.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    return ClaudeCreds(path=path, access_token=access, refresh_token=refresh, expires_at=expires_at)


def _write_back(creds: ClaudeCreds, access: str, refresh: str, expires_at: int) -> None:
    """Persist the rotated pair — the old refresh token is dead after use."""
    try:
        data = json.loads(creds.path.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    block = data.get("claudeAiOauth")
    if not isinstance(block, dict):
        block = {}
    block.update({"accessToken": access, "refreshToken": refresh, "expiresAt": expires_at})
    data["claudeAiOauth"] = block
    tmp = creds.path.with_name(creds.path.name + ".codexbar-tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, creds.path)


def _post_refresh(refresh_token: str) -> Optional[dict]:
    payload = json.dumps(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "codexbar-gui",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Claude OAuth refresh failed: %s", exc)
        return None
    if not isinstance(body, dict) or not body.get("access_token"):
        logger.warning("Claude OAuth refresh returned no access_token")
        return None
    return body


def refresh_credentials(creds: ClaudeCreds, now_ms: Optional[int] = None) -> Optional[ClaudeCreds]:
    global _last_refresh_fail
    if not creds.refresh_token:
        return None
    if time.monotonic() - _last_refresh_fail < REFRESH_RETRY_S:
        return None
    body = _post_refresh(creds.refresh_token)
    if body is None:
        _last_refresh_fail = time.monotonic()
        return None
    now = int(time.time() * 1000) if now_ms is None else now_ms
    access = str(body["access_token"])
    refresh = str(body.get("refresh_token") or creds.refresh_token)
    try:
        expires_at = now + int(float(body.get("expires_in") or 0)) * 1000
    except (TypeError, ValueError):
        expires_at = 0
    try:
        _write_back(creds, access, refresh, expires_at)
    except OSError:
        logger.warning("refreshed Claude token but could not write %s", creds.path)
    logger.info("refreshed Claude OAuth token from %s", creds.path.name)
    return ClaudeCreds(
        path=creds.path, access_token=access, refresh_token=refresh, expires_at=expires_at
    )


def access_token(now_ms: Optional[int] = None) -> Optional[str]:
    """Freshest usable Claude access token, refreshing on demand."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    found = [c for c in (read_credentials(p) for p in credential_paths()) if c is not None]
    if not found:
        return None
    found.sort(key=lambda c: c.expires_at, reverse=True)

    live = [c for c in found if c.access_token and not c.expired(now)]
    if live:
        return live[0].access_token

    for creds in found:
        fresh = refresh_credentials(creds, now_ms=now)
        if fresh is not None:
            return fresh.access_token
    # Expired but present: let the CLI try it — the API decides, not our clock.
    for creds in found:
        if creds.access_token:
            return creds.access_token
    return None


# --- multi-account bridge --------------------------------------------------
# The official CLI keeps multi-account tokens in ``providers[].tokenAccounts``
# of its own config (upstream docs/configuration.md) and fetches them all with
# ``codexbar usage --provider claude --all-accounts``. On Linux those tokens
# live in ccs profiles instead, so we mirror the freshest one per profile into
# that block and let upstream do the account handling.

ACCOUNT_NS = uuid.UUID("2a5f1d0e-9c3b-5f27-9a1d-3f7c6b2e8d41")


def is_ccs_owned(account: dict) -> bool:
    """True when ``account``'s id was derived by ``sync_token_accounts`` itself.

    Anything else (a different id, or an id from a manually-added account) is
    user-owned — the Settings editor lets a user add accounts by hand, and the
    sync must never delete those on the next poll.

    Case-insensitive: the official (Swift) CLI reformats UUIDs to uppercase
    when it rewrites the config (e.g. after ``codexbar config validate``),
    while Python's ``uuid5`` always renders lowercase — confirmed on the live
    machine's real config.json, where ccs-synced ids come back uppercase.
    """
    if not isinstance(account, dict):
        return False
    label = str(account.get("label") or "")
    return str(account.get("id") or "").lower() == str(uuid.uuid5(ACCOUNT_NS, label)).lower()


@dataclass
class ClaudeAccount:
    label: str
    creds: ClaudeCreds


def _account_label(path: Path) -> str:
    """Human label for a credential file: account email, else profile name."""
    for cand in (path.with_name(".claude.json"), path.parent.parent / ".claude.json"):
        try:
            data = json.loads(cand.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        email = str((data.get("oauthAccount") or {}).get("emailAddress") or "").strip()
        if email:
            return email
    parent = path.parent
    if parent.name == ".claude":
        parent = parent.parent
    if parent.parent.name == "instances":
        return parent.name
    return "default"


def discover_accounts(now_ms: Optional[int] = None) -> List[ClaudeAccount]:
    """One entry per distinct logged-in Claude profile, refreshed on demand."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    out: List[ClaudeAccount] = []
    seen_tokens = set()
    seen_labels = set()
    for path in credential_paths():
        creds = read_credentials(path)
        if creds is None:
            continue
        if creds.expired(now):
            creds = refresh_credentials(creds, now_ms=now) or creds
        if not creds.access_token or creds.access_token in seen_tokens:
            continue
        label = _account_label(path)
        if label in seen_labels:
            continue
        seen_tokens.add(creds.access_token)
        seen_labels.add(label)
        out.append(ClaudeAccount(label=label, creds=creds))
    return out


def official_config_path() -> Path:
    env = (os.environ.get("CODEXBAR_CONFIG") or "").strip()
    if env:
        return Path(env).expanduser()
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg.startswith("/"):
        return Path(xdg) / "codexbar" / "config.json"
    legacy = Path.home() / ".codexbar" / "config.json"
    default = Path.home() / ".config" / "codexbar" / "config.json"
    if legacy.is_file() and not default.is_file():
        return legacy
    return default


def sync_token_accounts(
    config_path: Optional[Path] = None,
    *,
    min_accounts: int = 2,
) -> List[str]:
    """Mirror ccs Claude profiles into the official ``tokenAccounts`` block.

    Returns the labels written; ``[]`` when fewer than ``min_accounts`` profiles
    are logged in (a single account keeps the ambient OAuth path).
    """
    accounts = discover_accounts()
    if len(accounts) < min_accounts:
        return []
    path = config_path or official_config_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    providers = data.get("providers")
    if not isinstance(providers, list):
        providers = []
    entry = next(
        (
            p
            for p in providers
            if isinstance(p, dict) and str(p.get("id") or "").lower() == "claude"
        ),
        None,
    )
    if entry is None:
        entry = {"id": "claude", "enabled": True}
        providers.append(entry)
    prev = entry.get("tokenAccounts")
    prev_list = list(prev.get("accounts") or []) if isinstance(prev, dict) else []
    prev_ccs_by_label = {
        str(row.get("label")): row
        for row in prev_list
        if isinstance(row, dict) and is_ccs_owned(row)
    }

    now_s = int(time.time())

    def _ccs_entry(a: ClaudeAccount) -> dict:
        prev_row = prev_ccs_by_label.get(a.label)
        if prev_row is not None and str(prev_row.get("token")) == a.creds.access_token:
            # Token didn't rotate — reuse the row so an unrelated re-sync
            # (nothing changed) compares equal to the on-disk state below.
            return prev_row
        return {
            "id": str(uuid.uuid5(ACCOUNT_NS, a.label)),
            "label": a.label,
            "token": a.creds.access_token,
            "addedAt": (prev_row or {}).get("addedAt") or now_s,
            "lastUsed": now_s,
        }

    ccs_accounts = {a.label: _ccs_entry(a) for a in accounts}

    # Rebuild in the on-disk order: ccs-owned rows get refreshed tokens (or are
    # dropped when that profile logged out); anything user-owned — a hand-added
    # account, or an id that doesn't match our uuid5 derivation — passes through
    # untouched so the sync never deletes what the Settings editor added.
    merged: List[dict] = []
    seen_labels: set[str] = set()
    for row in prev_list:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        if is_ccs_owned(row):
            if label in ccs_accounts:
                merged.append(ccs_accounts[label])
                seen_labels.add(label)
            # else: ccs profile no longer logged in — drop the stale row.
        else:
            merged.append(row)
            seen_labels.add(label)
    for a in accounts:
        if a.label not in seen_labels:
            merged.append(ccs_accounts[a.label])
            seen_labels.add(a.label)

    if merged == prev_list:
        # Nothing rotated — don't rewrite the config on every refresh tick.
        return [a.label for a in accounts]

    prev_active = prev.get("activeIndex") if isinstance(prev, dict) else None
    active_index = prev_active if isinstance(prev_active, int) and 0 <= prev_active < len(merged) else 0

    entry["enabled"] = True
    entry["tokenAccounts"] = {
        "version": 1,
        "activeIndex": active_index,
        "accounts": merged,
    }
    data["providers"] = providers
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".codexbar-tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    logger.info("synced %d Claude token accounts into %s", len(accounts), path.name)
    return [a.label for a in accounts]
