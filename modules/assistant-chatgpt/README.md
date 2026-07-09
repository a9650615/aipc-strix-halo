# assistant-chatgpt (multi-site web engine)

**Online backend** for the assistant aggregator: **one Playwright Chromium
engine**, **many site packs**. ChatGPT is the first pack; more sites =
more packs + `sites.yaml` entries, not a second browser stack.

Implements `backend.online` for `modules/assistant-aggregator`.

## Status

Ships **`.disabled`** by default (enable after first login + Voice hardware
check). Implementation is present: Playwright Chromium, inject/send,
turn --voice, session close.

```bash
# enable on a machine after verifying
rm modules/assistant-chatgpt/.disabled   # or image post-enable
pip install playwright && python -m playwright install chromium
aipc-chatgpt status
aipc-assistant mode online
aipc-assistant --text "hello" --prefer online
```

## Layout

```text
files/usr/bin/aipc-chatgpt
files/usr/lib/aipc_chatgpt/{backend,paths}.py
```

## Contract

CLI / `get_backend()` for aggregator:

- `inject --send` / `turn --voice` / `session close` / `voice stop` / `status`

Profile: `$XDG_DATA_HOME/aipc-chatgpt/profile` (not system Chrome).
CDP port: `AIPC_CHATGPT_CDP_PORT` default 9222 loopback.

## Auth / login session (no passwords)

Because the engine is **ours**, login is collected as **session state**, not
by scraping passwords:

| What | Where |
|---|---|
| Chromium profile (cookies DB, local storage) | `~/.local/share/aipc-chatgpt/profile` |
| Portable export | `~/.local/share/aipc-chatgpt/storage_state.json` (mode 0600) |

```bash
# 1) Open window; you log in manually in UI (Google / email / …)
aipc-chatgpt auth login --timeout 300

# 2) Check
aipc-chatgpt auth status

# 3) Export / import (migrate machine, backup — still secret!)
aipc-chatgpt auth export
aipc-chatgpt auth import --file /path/to/storage_state.json

# session close also best-effort re-exports
aipc-chatgpt session close
```

**Never** commit `storage_state.json` or the profile dir. Optional: encrypt
export with SOPS for backup (`docs/secrets-setup.md` pattern). Aggregator
status can show `logged_in` via online backend status.

See OpenSpec `assistant-chatgpt-online`.
