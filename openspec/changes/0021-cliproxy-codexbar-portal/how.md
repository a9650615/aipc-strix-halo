# How — cliproxy-codexbar-portal

## User bus from root portal

Portal runs as a system unit (often root) with
`Environment=AIPC_PRIMARY_USER=birdyo` (already set on this machine via
drop-in).

**Hardware finding (this host):** `systemctl --user -M birdyo@ …` works from an
interactive root shell and from short `systemd-run` oneshots, but fails when
spawned as a child of the long-running `aipc-portal.service` with:

```
Failed to start transient service unit: Connection reset by peer
```

So portal probes/starts user units via:

```sh
runuser -u birdyo -- env XDG_RUNTIME_DIR=/run/user/$(id -u birdyo) \
  systemctl --user is-active ccs-cliproxy.service
```

## Health URLs

- CLIProxy: `GET http://127.0.0.1:8317/` returns 200 + endpoint list (no key).
  Do **not** use `/v1/models` (401 without API key).
- CodexBar: `GET http://127.0.0.1:8080/health` returns `{"status":"ok",...}`.

## Live hotfix path

1. Edit repo files under `modules/...`.
2. Copy `registry.py` / `ops.py` → `/usr/local/lib/aipc-portal/aipc_portal/`.
3. Install cards into `/etc/aipc/portal/services/`.
4. User unit for CLIProxy: `~/.config/systemd/user/ccs-cliproxy.service`
   (immutable `/usr` cannot receive the unit until next bootc image).
5. Prefer module unit `aipc-usage.service` over hand-made
   `codexbar-usage-server.service` (same :8080).
6. `systemctl restart aipc-portal.service`.
7. Confirm `/api/v1/dashboard` lists `cliproxy` + `codexbar` as `active`.

## Tests

- Parse `systemd_scope` from YAML.
- `unit_is_active` / `start_unit` argv for user vs system (mocked runner).
- `service_group` for new ids.
- Existing control-center snapshot tests stay green.
