# Secrets Setup

aipc uses [SOPS](https://github.com/getsops/sops) with [age](https://age-encryption.org/) to encrypt secrets committed to the repo. Non-secret config keys stay plaintext so diffs remain readable; only values under matching keys are encrypted.

The Mac is the authoring machine. The AI PC holds a copy of the private key so it can decrypt at runtime.

---

## 1. Prerequisites

**Mac (authoring):**

```sh
brew install sops age
```

**AI PC (runtime):** sops and age are installed by the `secrets-sops` module via `rpm-ostree`. No manual install needed.

---

## 2. Key Generation

Generate once on the Mac. The private key never leaves `~/.config/aipc/`.

```sh
mkdir -p ~/.config/aipc
age-keygen -o ~/.config/aipc/age.key
chmod 600 ~/.config/aipc/age.key
```

Paste the printed public key into `.sops.yaml` under `creation_rules[0].age`:

```yaml
creation_rules:
  - path_regex: secrets/.*\.yaml$
    age: age1YOUR_PUBLIC_KEY_HERE
    encrypted_regex: >-
      (_key|_token|_secret|^api_|^data$|^stringData$)
```

Commit `.sops.yaml`. Current repo public key: `age1kj9fxk3nkzedjdq3tfvtx22vfkjm57fysy5r5w007cn39355gpnqel46pm`.

---

## 3. Encrypting a New Secret

1. Create plaintext `secrets/something.yaml`. Use matching key names (`_key`, `_token`, `_secret`, `api_` prefix) for secret values.
2. Encrypt in place:

```sh
SOPS_AGE_KEY_FILE=~/.config/aipc/age.key sops --encrypt --in-place secrets/something.yaml
```

3. Commit. Matching-key values are now `ENC[AES256_GCM,...]`; others stay plaintext.

Save typing per shell: `export SOPS_AGE_KEY_FILE=~/.config/aipc/age.key`.

---

## 4. Editing an Encrypted File

SOPS decrypts to a temp editor buffer and re-encrypts on save:

```sh
SOPS_AGE_KEY_FILE=~/.config/aipc/age.key sops --edit secrets/something.yaml
```

Do not hand-edit `ENC[...]` ciphertext — SOPS rejects the file on next decrypt (MAC mismatch).

---

## 5. Decrypting

```sh
SOPS_AGE_KEY_FILE=~/.config/aipc/age.key sops --decrypt secrets/something.yaml
SOPS_AGE_KEY_FILE=~/.config/aipc/age.key sops --decrypt --output /tmp/plain.yaml secrets/something.yaml
```

Never write decrypted output anywhere under the repo.

---

## 6. Transferring to the AI PC

**Public key** — any channel. Paste, email, or commit to `.sops.yaml`.

**Private key** — USB only. Never over network, cloud sync, or chat.

```sh
# Mac → USB
cp ~/.config/aipc/age.key /Volumes/USB/aipc-age.key

# AI PC: install root-owned, then wipe the USB copy
sudo install -m 0600 -o root -g root /run/media/.../USB/aipc-age.key /etc/aipc/age.key
rm /run/media/.../USB/aipc-age.key
```

`modules/secrets-sops/` reads `/etc/aipc/age.key` during post-install to decrypt values into service env files.

---

## 7. Rotation

1. Generate a fresh keypair on the Mac: `age-keygen -o ~/.config/aipc/age.key.new`.
2. Update `.sops.yaml` with the new public key.
3. Re-wrap every secret file against the new key:
   ```sh
   for f in secrets/*.yaml; do
     SOPS_AGE_KEY_FILE=~/.config/aipc/age.key sops rotate --in-place "$f"
   done
   ```
4. Commit `.sops.yaml` and the re-encrypted files. Push.
5. Replace `/etc/aipc/age.key` on the AI PC via USB (§6), then re-run the secrets module post-install.
6. Securely delete the old Mac key: `rm -P ~/.config/aipc/age.key` (macOS) or `shred -u` (Linux).

---

## 8. Recovery

**There is no recovery without the private key.** SOPS + age is not escrowed.

- Mac key lost, AI PC key intact: copy the AI PC key back to the Mac via USB (reverse of §6).
- Both copies lost: every encrypted value is unrecoverable. Delete the files, generate a new keypair, re-enter plaintext secrets from source (password manager, upstream service), re-encrypt, and rotate every affected credential at its issuer.

Back up `~/.config/aipc/age.key` accordingly. Password-manager attachment or offline USB in a safe: yes. Cloud-synced plaintext copy: no.

---

## 9. The `encrypted_regex`

```yaml
encrypted_regex: >-
  (_key|_token|_secret|^api_|^data$|^stringData$)
```

SOPS can encrypt every value in a file, or only values under keys matching a regex. aipc uses the regex.

**Why:** most secret files carry metadata — service name, host, port, model ID — that is not itself secret. Leaving it plaintext means `git diff` on a secrets change shows what actually changed without a decrypt round-trip, code review can inspect structure, and the file doubles as documentation for "what does this service need".

**What matches:**

- `_key` suffix → `api_key`, `openai_key`, …
- `_token` suffix → `auth_token`, `github_token`, …
- `_secret` suffix → `client_secret`, …
- `api_` prefix → `api_endpoint`, `api_key`, …
- Exact `data` or `stringData` (top-level) → Kubernetes Secret convention.

**What does not:** `host`, `port`, `model`, `enabled`, `name` — not secret, stays plaintext.

**Rule of thumb:** name any new secret field with `_key` / `_token` / `_secret` suffix or `api_` prefix. If a non-obvious name is needed, extend the regex in `.sops.yaml` and re-encrypt affected files.
