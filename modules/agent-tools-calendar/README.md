# agent-tools-calendar

Calendar/email integration (D8): Google Calendar (OAuth2), Proton (via
Proton Bridge), Fastmail (IMAP + CalDAV). No secrets are baked into the
image — every credential is written by hand, at firstboot, by the user.

## Package

`files/usr/lib/aipc-agent/aipc_agent_tools_calendar/` — an importable
package (mirrors `agent-tools-files`'s layout):

- `backends.py` — the three backends + `lookup_events(query)` /
  `lookup_email(query)`, the public functions `daily_assistant.py`'s
  `calendar_lookup`/`email_lookup` tools call. Each returns
  `{"status": "ok"/"not_configured"/"error", ...}`.
- Every library/network boundary (`yaml`, `google-api-python-client`,
  `google-auth-oauthlib`, `urllib`, `imaplib`) is imported lazily inside
  the function that needs it, guarded by `try/except ImportError` — the
  package always imports cleanly and fails closed to `not_configured`
  instead of crashing.

## Backends

### Google Calendar (task 4.2)
OAuth2 via `google-api-python-client` + `google-auth-oauthlib`
(`InstalledAppFlow`). Provisioned at firstboot:

```
aipc agent oauth google --client-secret /path/to/client_secret.json
```

Token is stored at `/var/lib/aipc-agent/oauth/google.json`, `0600`,
user-owned, refreshed automatically on read when expired. Calendar-only
in this build — no Gmail scope is requested, so `lookup_email()` reports
`not_configured` for the google backend even when it's enabled.

**Not exercised live in this repo** — no Google OAuth client credentials
exist in this environment. Token storage/refresh/read paths are covered
by `backends.self_test()` instead, with a stubbed `google.oauth2`/
`google.auth` module standing in for the real library.

### Proton (task 4.3)
Requires [Proton Bridge](https://proton.me/mail/bridge) running locally.
Bridge exposes a local IMAP endpoint (port shown in the Bridge app, varies
by install — the default in `calendar.yaml` is `127.0.0.1:1143`). Proton
does not publish a fixed CalDAV port/path; `caldav_url` must be filled in
from your own Bridge instance's settings before enabling this provider.

### Fastmail (task 4.4)
IMAP (`imap.fastmail.com:993`) + CalDAV
(`https://caldav.fastmail.com/dav/calendars/user/<username>/Default`)
using an [app password](https://www.fastmail.help/hc/en-us/articles/360058752854)
— never your account password.

### CalDAV implementation note
Calendar queries against Proton/Fastmail use a minimal stdlib CalDAV
`REPORT` (`urllib.request` + Basic auth) and a line-based VEVENT scanner
— not `python3-caldav`/`python3-icalendar`. This covers keyword search
over `SUMMARY`/`DESCRIPTION`; it doesn't expand recurring events or
handle RFC 5545 line-folding. Swap in `python3-icalendar` if a caller
ever needs full fidelity.

## Secrets — never baked

- Google: OAuth token at `/var/lib/aipc-agent/oauth/google.json` (`0600`),
  written only by `aipc agent oauth google`, run by the user post-boot.
- Proton/Fastmail: `calendar.yaml`'s `password_file` fields point at
  `/var/lib/aipc-agent/secrets/{proton_bridge,fastmail_app}_password`
  (`0700` dir, created empty by `post-install.sh`) — the user creates
  these files by hand at firstboot; nothing is ever written to them at
  build time.

## Known gap — orchestrator venv visibility

`agent-orchestrator`'s venv (`/usr/lib/aipc-agent/venv`) is created
without `--system-site-packages`, so the `python3-google-api-client` /
`python3-google-auth-oauthlib` RPMs in this module's `packages.txt` (system
site-packages) aren't automatically visible to `daily_assistant.py` when
it calls the google backend from inside that venv. The lazy-import +
`ImportError` guard means this degrades to a clean `not_configured`
response rather than a crash — but making the Google backend actually
usable end-to-end needs either the venv to gain
`--system-site-packages`, or these two packages pip-installed into
`/usr/lib/aipc-agent/venv` directly. Left as a follow-up rather than
touched here — `agent-orchestrator/**` is out of scope for this change.

## Dependencies
- llm-litellm
- agent-orchestrator (daily_assistant.py wires `lookup_events`/`lookup_email`
  in as the real backend behind `calendar_lookup`/`email_lookup`)
- secrets-sops (not used directly — credentials here are user-written
  runtime files, not SOPS-encrypted repo secrets; see CLAUDE.md §5)

## Spec
openspec/changes/phase-4-agent — tasks 1.6, 4.2, 4.3, 4.4
