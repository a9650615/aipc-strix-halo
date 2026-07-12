# How — hermes-webui-module

## Runtime model (why user service, not system)

A **system** unit that execs from `/home` or reads `~/.hermes` is blocked by
SELinux (`init_t` → `user_home_t`): a system attempt failed with
`Failed to load environment files: Permission denied` / result `resources`
(same class as the repo's recurring venv `203/EXEC`). A **user** unit runs in the
user's own SELinux context, so exec of the agent-venv python and reads of
`~/.hermes` are allowed — this is the configuration already proven live in 0009.

Auto-start on boot = shipped `default.target.wants` symlink (enables the unit
image-wide) + `enable-linger` (starts the user manager at boot without a login).

## Python

`bootstrap.py --foreground` calls `os.execv(python_exe, [python_exe, server.py])`,
where `python_exe` defaults to the agent venv. The unit both launches with and
sets `HERMES_WEBUI_PYTHON` to `%h/.hermes/hermes-agent/venv/bin/python`
(3.11, verified to carry yaml 6.0.3 + cryptography 46.0.7). We do NOT depend on
`~/.local/bin/python3.11` (uv-managed, user-specific, absent on a fresh image).

## First-boot setup

`setup-hermes-webui.sh` follows `ops-firstboot/aipc-init`: resolve user via
`awk -F: '$3>=1000 && $3<60000'`, act via
`runuser -u "$user" -- env HOME=… XDG_RUNTIME_DIR=/run/user/$uid …`. Sentinel
`/var/lib/aipc/hermes-webui-setup.pin` stores the applied pin; the script early-
exits when it matches and the checkout is present, so normal boots are cheap and
offline-safe (network failures are tolerated with `|| true`).

## Render parity (§4)

All files are plain module files copied identically by both renderers (the
`default.target.wants` symlink is preserved by COPY). No renderer special-casing.

## Verification

- Static: `sh -n` on scripts, `systemd-analyze verify` on units if available,
  `pytest` (repo suite unaffected).
- Render: `aipc render bootc` + `aipc render ansible`, both include the module
  symmetrically.
- Hardware: NOT fully verifiable in-session (needs a fresh image boot to exercise
  the setup oneshot + auto-enable). The runtime pattern (this unit + linger +
  agent-venv python) is already hardware-proven by the live 0009 user service.
