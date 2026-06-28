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

## Cloud LLM key decryption (runtime)

`aipc-decrypt-cloud-keys.service` is a oneshot that runs `Before=litellm.service`.
It decrypts `/etc/aipc/secrets/cloud-llm.yaml` (if present) using `/etc/aipc/age.key`
and writes `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` lines into
`/etc/aipc/env.d/llm-litellm/cloud-keys.env` (mode 0600 root:root). The litellm
quadlet loads this file via `EnvironmentFile=-`.

`ConditionPathExists` makes the unit a no-op when the encrypted file is absent;
the helper script also exits 0 if the age key is absent. Cloud keys are optional.

Files:

- `/etc/systemd/system/aipc-decrypt-cloud-keys.service` — the oneshot unit.
- `/usr/lib/aipc/decrypt-cloud-keys.sh` — the helper script.

`cloud-llm.yaml` value format: bare strings, no quotes (e.g. `anthropic_api_key: sk-ant-...`)
— quotes carry through into the env file. See `secrets/cloud-llm.yaml.example`.
