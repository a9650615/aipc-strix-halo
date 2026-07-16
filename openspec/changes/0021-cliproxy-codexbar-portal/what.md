# What — cliproxy-codexbar-portal

## system-aipc-portal

- Extend service metadata with optional `systemd_scope: system|user`
  (default `system` — backward compatible).
- `unit_is_active` / `start_unit` honour scope:
  - system → `systemctl <action> <unit>` (+ sudo fallback as today)
  - user → `systemctl --user -M <AIPC_PRIMARY_USER>@ <action> <unit>`
- `service_group`:
  - `cliproxy` → LLM
  - `codexbar` → Agent
- Snapshot continues to expose `state` / `health` / `can_start` / `group`;
  SPA needs no structural change.

## Service cards

| id | module | unit | scope | health | ui |
|---|---|---|---|---|---|
| `cliproxy` | `ccs` | `ccs-cliproxy.service` | user | `http://127.0.0.1:8317/` | null |
| `codexbar` | `dev-ai-codexbar-usage` | `aipc-usage.service` | user | `http://127.0.0.1:8080/health` | `http://127.0.0.1:8080/` |

No secrets on cards (no OAuth paths, no management API keys).

## ccs module

- Ship `files/usr/lib/systemd/user/ccs-cliproxy.service` (binary under
  `~/.ccs/cliproxy`, config under same tree — user-owned).
- Portal card under `files/etc/aipc/portal/services/cliproxy.yaml`.

## dev-ai-codexbar-usage

- Portal card under `files/etc/aipc/portal/services/codexbar.yaml`
  pointing at the existing user unit `aipc-usage.service`.

## Out of scope

- Changing peer-agents MCP / Hermes SOUL (separate collab work).
- Baking CLIProxy binary into the image (still CCS-installed under home).
- Management API / secret-key UI for CLIProxy.
