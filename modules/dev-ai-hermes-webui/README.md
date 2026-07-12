# dev-ai-hermes-webui

Reproducible integration of [`nesquena/hermes-webui`](https://github.com/nesquena/hermes-webui)
— the web console for NousResearch `hermes-agent` — into the AIPC image.

## Purpose

Hermes is the heavyweight agent the voice orchestrator delegates tool-heavy
turns to. hermes-webui is a turnkey chat + session-monitor + workspace UI for it.
Its CLI-session bridge reads `hermes-agent`'s `state.db`, so voice-dispatched
`source_tag: aipc-voice` sessions appear in its sidebar. It reuses
`~/.hermes/config.yaml`, so model calls still route through LiteLLM (CLAUDE.md §7).

## What this module ships (integration, not a frozen copy)

hermes-webui **self-updates (git)** and is **deeply coupled to `hermes-agent`**
(`api/config.py` puts the agent dir on `sys.path` and imports `hermes_cli` /
`run_agent` in-process, so the server runs inside the agent venv). `hermes-agent`
itself is a user-home checkout, not baked into the image. Freezing a
self-updating, home-coupled app into read-only `/usr/lib` would fight all of that,
so this module owns the **integration**:

- `usr/lib/systemd/user/hermes-webui.service` — user unit; runs the server under
  the agent venv python (`~/.hermes/hermes-agent/venv/bin/python`, 3.11, carries
  pyyaml + cryptography). Dormant until the checkout + agent venv exist.
- `usr/lib/systemd/user/default.target.wants/…` — auto-enable symlink.
- `usr/lib/aipc/hermes-webui/setup-hermes-webui.sh` + `aipc-hermes-webui-setup.service`
  — runtime oneshot: clone/update `~/.hermes/hermes-webui` at the pinned ref,
  `enable-linger`, start the user unit. Idempotent, offline-safe, sentinel by pin.
- `etc/aipc/portal/services/hermes-webui.yaml` — Control Center card (Open UI → :8788).

Bound to `127.0.0.1:8788` (default 8787 is taken by codexbar-gui).

## Dependencies

- **hermes-agent** at `~/.hermes/hermes-agent` (user-home tool, not shipped here).
  The user unit stays dormant if it is absent.
- Runtime network on first boot (or on a pin change) to clone/update the checkout.

## Why a user service (not system)

A system unit that execs from `/home` or reads `~/.hermes` is denied by SELinux
(`init_t` → `user_home_t`). A user unit runs in the user's own context — the
configuration proven live in OpenSpec change 0009.

## Pinned version

`exp-v0.52.39`. Bump `PIN` in `setup-hermes-webui.sh` to update; the oneshot
re-runs when the pin changes.

## Remote / phone access

Not shipped. For phone access use Tailscale: `tailscale serve --bg --http=8788
http://127.0.0.1:8788` keeps the server on loopback and reaches it over the
tailnet only (never the public internet — Hermes runs `--yolo`).

## Verification

`verify.sh` checks the shipped files and, if a server is up, probes
`:8788/health`; exits `2` (OPTIONAL) when not yet provisioned. Full runtime
verification needs a fresh image boot to exercise the setup oneshot.
