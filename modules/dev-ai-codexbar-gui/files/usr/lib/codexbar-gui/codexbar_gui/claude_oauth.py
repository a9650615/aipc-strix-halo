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
