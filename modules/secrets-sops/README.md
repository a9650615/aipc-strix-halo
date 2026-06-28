# secrets-sops

Installs the SOPS system configuration and the `sops-env` helper that sources
decrypted YAML values as `SECRET_*` environment variables.

## What it does

- Installs `/etc/aipc/sops.yaml` (SOPS creation rules; age public key managed separately).
- Installs `/usr/lib/aipc/sops-env` (sourceable helper, mode 0755).
- `post-install.sh` ensures correct permissions on the helper.

## Runtime behaviour

Source `/usr/lib/aipc/sops-env <encrypted-yaml>` to load `SECRET_*` vars.
If `/etc/aipc/age.key` (the private key, installed out-of-band) is absent, the
helper writes a diagnostic to stderr and exits non-zero — it never silently skips.

## Dependencies

- `secrets-sops` depends on `system-base` (for `sops` and `age` binaries).

## Key management

The age **private** key (`/etc/aipc/age.key`, mode 0400) is installed manually
by the operator; it is never in this repo or in CI.

See `docs/secrets-setup.md` for key generation, USB transfer, and rotation.
