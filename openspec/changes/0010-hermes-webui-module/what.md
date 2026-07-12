# What — hermes-webui-module

New module `modules/dev-ai-hermes-webui/` (dev-ai category). Ships integration
only; the app + agent stay home checkouts.

## Files

- `files/usr/lib/systemd/user/hermes-webui.service` — user unit. Runs the server
  under the **agent venv python** with `bootstrap.py --foreground` (bootstrap
  `os.execv`s the real server). `ConditionPathExists=%h/.hermes/hermes-webui/bootstrap.py`
  so it stays dormant (no crash-loop) until the checkout exists. HOST=127.0.0.1,
  PORT=8788.
- `files/usr/lib/systemd/user/default.target.wants/hermes-webui.service` —
  symlink that auto-enables the user unit image-wide.
- `files/usr/lib/aipc/hermes-webui/setup-hermes-webui.sh` — resolves the primary
  user (uid ≥1000), `enable-linger`, clones/updates `~/.hermes/hermes-webui` to
  the pinned ref (`exp-v0.52.39`), then starts the user unit. Idempotent;
  re-runs only when the pin changes or the checkout is missing.
- `files/etc/systemd/system/aipc-hermes-webui-setup.service` — oneshot,
  `After/Wants=network-online.target`, runs the setup script at boot.
- `files/etc/aipc/portal/services/hermes-webui.yaml` — **moved here** from
  `agent-orchestrator` (correct ownership; avoids a duplicate card id).

- `post-install.sh` — build-time only: chmod scripts, `systemctl enable
  aipc-hermes-webui-setup.service`. No `--now`, no network, no health checks.
- `packages.txt`, `README.md`, `verify.sh`.

## Removed

- `modules/agent-orchestrator/files/etc/aipc/portal/services/hermes-webui.yaml`
  (relocated into this module).

## Out of scope

- Baking the webui source or a venv into `/usr/lib` (rejected: self-updating +
  home-coupled).
- Packaging hermes-agent (remains a user-home tool).
- Remote/phone exposure (Tailscale) — user runtime config, documented not shipped.
