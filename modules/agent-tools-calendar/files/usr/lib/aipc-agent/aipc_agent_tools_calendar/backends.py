"""Calendar/email backends for agent-tools-calendar (phase-4-agent#1.6, 4.2-4.4).

Three backends behind one lookup_events()/lookup_email() surface, config-
selected from /etc/aipc/agent/calendar.yaml:

- google:   Google Calendar via OAuth2 (google-api-python-client). Token
  lives at /var/lib/aipc-agent/oauth/google.json (0600, user-owned), written
  by `aipc agent oauth google` at firstboot -- never baked into the image.
  Calendar only in this build; Gmail is not wired (see lookup_email()).
- proton:   Proton Bridge's local IMAP endpoint + a CalDAV endpoint (URL is
  environment-specific -- see README). Bridge must already be running.
- fastmail: Fastmail's public IMAP + CalDAV endpoints, authenticated with
  an app password the user creates at firstboot (never baked).

CalDAV access is a minimal stdlib REPORT query + line-based VEVENT scan
instead of a python3-caldav/icalendar dependency: the surface we need
(calendar-query REPORT, VEVENT SUMMARY/DTSTART/DTEND) is a few dozen lines
of urllib, not a new dependency (ponytail: add python3-icalendar if a
caller ever needs full RFC 5545 fidelity -- recurrence expansion, folded
lines, timezones).

Every network/library boundary (yaml, google-api-python-client,
google-auth-oauthlib, urllib, imaplib) is imported lazily inside the
function that needs it and guarded with try/except ImportError, so the
package always imports cleanly and degrades to a structured
"not_configured"/"error" response instead of crashing -- same contract as
aipc_agent_tools_files.read_file's ImportError fallback in daily_assistant.py.
"""

import base64
import json
import os
from pathlib import Path

DEFAULT_CONFIG_PATH = "/etc/aipc/agent/calendar.yaml"
OAUTH_DIR = "/var/lib/aipc-agent/oauth"
GOOGLE_TOKEN_PATH = f"{OAUTH_DIR}/google.json"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

_CALDAV_QUERY_BODY = (
    '<?xml version="1.0" encoding="utf-8" ?>'
    '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
    "<D:prop><D:getetag/><C:calendar-data/></D:prop>"
    '<C:filter><C:comp-filter name="VCALENDAR">'
    '<C:comp-filter name="VEVENT"/></C:comp-filter></C:filter>'
    "</C:calendar-query>"
)


def _load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _provider_config(config: dict, name: str) -> dict:
    return (config.get("providers") or {}).get(name) or {}


def _read_secret_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return Path(path).read_text().strip() or None
    except OSError:
        return None


# --- Google Calendar (task 4.2) ---------------------------------------


def _store_google_token(creds, token_path: str = GOOGLE_TOKEN_PATH) -> None:
    p = Path(token_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(creds.to_json())
    os.chmod(p, 0o600)


def _google_credentials(token_path: str = GOOGLE_TOKEN_PATH):
    """Load + refresh stored Google credentials. None if never provisioned."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    try:
        data = json.loads(Path(token_path).read_text())
    except (OSError, ValueError):
        return None
    creds = Credentials.from_authorized_user_info(data, GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _store_google_token(creds, token_path)
    return creds


def run_google_oauth_flow(
    client_secret_path: str,
    token_path: str = GOOGLE_TOKEN_PATH,
    scopes: list[str] = GOOGLE_SCOPES,
) -> dict:
    """Interactive consent flow -- the body of `aipc agent oauth google`.

    NOT exercised live in this repo (no Google OAuth client credentials
    exist here); token storage/refresh/read paths are self-tested instead.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, scopes)
    creds = flow.run_local_server(port=0)
    _store_google_token(creds, token_path)
    return {"status": "ok", "detail": f"token stored at {token_path}"}


def _google_lookup_events(query: str, token_path: str = GOOGLE_TOKEN_PATH) -> dict:
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return {
            "status": "not_configured",
            "tool": "calendar",
            "provider": "google",
            "detail": "google-api-python-client not installed in this interpreter",
        }
    creds = _google_credentials(token_path)
    if creds is None:
        return {
            "status": "not_configured",
            "tool": "calendar",
            "provider": "google",
            "detail": "no Google OAuth token yet -- run `aipc agent oauth google`",
        }
    try:
        service = build("calendar", "v3", credentials=creds)
        resp = (
            service.events()
            .list(calendarId="primary", q=query, maxResults=10, singleEvents=True, orderBy="startTime")
            .execute()
        )
        events = [
            {"summary": e.get("summary", ""), "start": e.get("start", {}), "end": e.get("end", {})}
            for e in resp.get("items", [])
        ]
        return {"status": "ok", "tool": "calendar", "provider": "google", "events": events}
    except Exception as exc:  # network/API errors -- report, don't crash the tool call
        return {"status": "error", "tool": "calendar", "provider": "google", "detail": str(exc)}


# --- CalDAV (proton + fastmail calendars, task 4.3/4.4) ----------------


def _caldav_report(url: str, username: str, password: str, timeout: float = 10.0) -> str:
    import urllib.request

    req = urllib.request.Request(url, data=_CALDAV_QUERY_BODY.encode(), method="REPORT")
    req.add_header("Content-Type", "application/xml; charset=utf-8")
    req.add_header("Depth", "1")
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_vevents(raw: str) -> list[dict]:
    """Pull SUMMARY/DTSTART/DTEND/UID/DESCRIPTION out of VEVENT blocks with
    a line-based scan. Doesn't handle RFC 5545 line folding or recurrence
    expansion -- good enough for a keyword-search tool (ponytail: swap in
    python3-icalendar if a caller needs full fidelity)."""
    events: list[dict] = []
    current: dict | None = None
    for line in raw.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, _, value = line.partition(":")
            key = key.split(";")[0]
            if key in ("SUMMARY", "DTSTART", "DTEND", "UID", "DESCRIPTION"):
                current[key.lower()] = value
    return events


def _caldav_lookup_events(query: str, url: str, username: str, password: str) -> dict:
    if not url:
        return {"status": "error", "tool": "calendar", "detail": "caldav_url not configured"}
    try:
        raw = _caldav_report(url, username, password)
    except Exception as exc:
        return {"status": "error", "tool": "calendar", "detail": str(exc)}
    matched = [
        e
        for e in parse_vevents(raw)
        if query.lower() in (e.get("summary", "") + e.get("description", "")).lower()
    ]
    return {"status": "ok", "tool": "calendar", "events": matched}


# --- IMAP (proton + fastmail email, task 4.3/4.4) ----------------------


def _imap_lookup_email(
    query: str,
    host: str,
    port: int,
    username: str,
    password: str,
    mailbox: str = "INBOX",
    client_cls=None,
) -> dict:
    import imaplib

    client_cls = client_cls or imaplib.IMAP4_SSL
    if not host or not username:
        return {"status": "error", "tool": "email", "detail": "imap_host/username not configured"}
    try:
        with client_cls(host, port) as imap:
            imap.login(username, password)
            imap.select(mailbox, readonly=True)
            typ, data = imap.search(None, "TEXT", f'"{query}"')
            if typ != "OK":
                return {"status": "error", "tool": "email", "detail": f"IMAP SEARCH failed: {typ}"}
            ids = data[0].split()[:10] if data and data[0] else []
            results = []
            for msg_id in ids:
                typ, msg_data = imap.fetch(msg_id, "(BODY[HEADER.FIELDS (SUBJECT FROM DATE)])")
                if typ == "OK" and msg_data and msg_data[0]:
                    results.append(msg_data[0][1].decode("utf-8", errors="replace").strip())
            return {"status": "ok", "tool": "email", "results": results}
    except Exception as exc:
        return {"status": "error", "tool": "email", "detail": str(exc)}


# --- Public dispatch (matches daily_assistant.py's calendar_lookup/email_lookup) ---


def lookup_events(query: str, config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Search calendar events matching `query` on whichever backend is
    enabled in calendar.yaml. Precedence: google, then proton, then
    fastmail (first enabled wins)."""
    config = _load_config(config_path)

    google_cfg = _provider_config(config, "google")
    if google_cfg.get("enabled"):
        return _google_lookup_events(query)

    for name in ("proton", "fastmail"):
        cfg = _provider_config(config, name)
        if not cfg.get("enabled"):
            continue
        password = _read_secret_file(cfg.get("password_file"))
        if password is None:
            return {
                "status": "error",
                "tool": "calendar",
                "provider": name,
                "detail": f"{name} enabled but password_file is missing/unreadable",
            }
        return _caldav_lookup_events(query, cfg.get("caldav_url", ""), cfg.get("username", ""), password)

    return {
        "status": "not_configured",
        "tool": "calendar",
        "detail": "no calendar backend enabled in /etc/aipc/agent/calendar.yaml",
    }


def lookup_email(query: str, config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Search email matching `query`. Google is calendar-only in this
    build (no Gmail scope requested), so only proton/fastmail serve
    email."""
    config = _load_config(config_path)

    for name in ("proton", "fastmail"):
        cfg = _provider_config(config, name)
        if not cfg.get("enabled"):
            continue
        password = _read_secret_file(cfg.get("password_file"))
        if password is None:
            return {
                "status": "error",
                "tool": "email",
                "provider": name,
                "detail": f"{name} enabled but password_file is missing/unreadable",
            }
        return _imap_lookup_email(
            query, cfg.get("imap_host", ""), int(cfg.get("imap_port", 993) or 993), cfg.get("username", ""), password
        )

    if _provider_config(config, "google").get("enabled"):
        return {
            "status": "not_configured",
            "tool": "email",
            "provider": "google",
            "detail": "google backend is calendar-only in this build (phase-4-agent#4.2)",
        }
    return {
        "status": "not_configured",
        "tool": "email",
        "detail": "no email backend enabled in /etc/aipc/agent/calendar.yaml",
    }


def self_test() -> None:
    """ponytail: one runnable check per backend boundary -- config load,
    google token store/read/refresh, CalDAV VEVENT parsing, dispatch
    precedence, and the ImportError fallback. No live network."""
    import sys
    import tempfile
    import types

    # --- config load: missing file -> {} , real file -> parsed ---
    assert _load_config("/nonexistent/calendar.yaml") == {}
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "calendar.yaml"
        cfg_path.write_text("providers:\n  fastmail:\n    enabled: true\n    username: x\n")
        loaded = _load_config(str(cfg_path))
        assert loaded["providers"]["fastmail"]["enabled"] is True

    # --- google: no google-api-python-client installed here -> not_configured ---
    assert "googleapiclient" not in sys.modules
    result = _google_lookup_events("standup")
    assert result["status"] == "not_configured", result

    # --- google token store/read round-trip with a fake Credentials-shaped object ---
    with tempfile.TemporaryDirectory() as tmp:
        token_path = str(Path(tmp) / "google.json")

        class _FakeCreds:
            def to_json(self):
                return json.dumps({"token": "abc", "refresh_token": "r"})

        _store_google_token(_FakeCreds(), token_path)
        assert Path(token_path).exists()
        assert oct(Path(token_path).stat().st_mode)[-3:] == "600"
        stored = json.loads(Path(token_path).read_text())
        assert stored["token"] == "abc"

    # --- google_credentials with stubbed google.oauth2/google.auth modules ---
    fake_google_oauth2 = types.ModuleType("google.oauth2")
    fake_google_oauth2_credentials = types.ModuleType("google.oauth2.credentials")
    fake_google_auth = types.ModuleType("google.auth")
    fake_google_auth_transport = types.ModuleType("google.auth.transport")
    fake_google_auth_transport_requests = types.ModuleType("google.auth.transport.requests")

    class _StubCredentials:
        def __init__(self, expired=False):
            self.expired = expired
            self.refresh_token = "r"
            self.refreshed = False

        @classmethod
        def from_authorized_user_info(cls, data, scopes):
            return cls(expired=data.get("expired", False))

        def to_json(self):
            return json.dumps({"token": "refreshed"})

        def refresh(self, request):
            self.refreshed = True

    fake_google_oauth2_credentials.Credentials = _StubCredentials
    fake_google_auth_transport_requests.Request = lambda: object()

    saved_modules = {
        k: sys.modules.get(k)
        for k in (
            "google.oauth2",
            "google.oauth2.credentials",
            "google.auth",
            "google.auth.transport",
            "google.auth.transport.requests",
        )
    }
    sys.modules["google.oauth2"] = fake_google_oauth2
    sys.modules["google.oauth2.credentials"] = fake_google_oauth2_credentials
    sys.modules["google.auth"] = fake_google_auth
    sys.modules["google.auth.transport"] = fake_google_auth_transport
    sys.modules["google.auth.transport.requests"] = fake_google_auth_transport_requests
    try:
        with tempfile.TemporaryDirectory() as tmp:
            token_path = str(Path(tmp) / "google.json")
            Path(token_path).write_text(json.dumps({"expired": True}))
            creds = _google_credentials(token_path)
            assert creds is not None and creds.refreshed is True
    finally:
        for k, v in saved_modules.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    # --- CalDAV VEVENT parsing ---
    sample_ics = (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\nUID:1\nSUMMARY:Team standup\nDTSTART:20260710T090000Z\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:2\nSUMMARY:Dentist\nDTSTART:20260711T140000Z\nEND:VEVENT\n"
        "END:VCALENDAR\n"
    )
    events = parse_vevents(sample_ics)
    assert len(events) == 2
    assert events[0]["summary"] == "Team standup"
    assert events[1]["uid"] == "2"

    # --- dispatch precedence + password_file gating (no real IMAP/CalDAV call) ---
    with tempfile.TemporaryDirectory() as tmp:
        secret = Path(tmp) / "fastmail_app_password"
        secret.write_text("app-pw\n")
        cfg_path = Path(tmp) / "calendar.yaml"
        cfg_path.write_text(
            "providers:\n"
            "  google:\n    enabled: false\n"
            "  proton:\n    enabled: false\n"
            "  fastmail:\n"
            "    enabled: true\n"
            f"    password_file: {secret}\n"
            "    caldav_url: ''\n"
            "    imap_host: ''\n"
            "    username: bob\n"
        )
        # caldav_url empty -> _caldav_lookup_events returns a clean error, not a crash
        result = lookup_events("dentist", str(cfg_path))
        assert result["status"] == "error" and "caldav_url" in result["detail"], result
        # imap_host empty -> same clean-error contract
        result = lookup_email("dentist", str(cfg_path))
        assert result["status"] == "error" and "imap_host" in result["detail"], result

    # --- no backend enabled -> not_configured, matches the pre-existing stub shape ---
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "calendar.yaml"
        cfg_path.write_text("providers:\n  google:\n    enabled: false\n")
        assert lookup_events("x", str(cfg_path))["status"] == "not_configured"
        assert lookup_email("x", str(cfg_path))["status"] == "not_configured"

    print("self-test passed")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
