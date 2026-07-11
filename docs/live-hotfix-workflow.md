# Live Hotfix Workflow — Testing a Change on the Running Machine Without a Rebuild

This repo's real deployment path is: edit a module under `modules/*/files/...` → render →
`bootc switch` → reboot → hardware-verify (CLAUDE.md §9). That loop is correct but slow
(minutes per iteration, and a reboot). This doc covers the *other* loop actually used
throughout this project's agent-log history: patching the already-running machine directly
so a fix can be hardware-verified in seconds, with the repo file as the durable source of
truth that survives the next real rebuild.

**This is a debugging/iteration shortcut, not a replacement for the real deploy path.**
Anything hand-patched into `/etc/` or a running unit is lost on `bootc switch` unless the
same content also lives in the matching `modules/*/files/...` path in the repo — always
edit the repo file first, then copy it live, never the other way around.

**Close the layer loop when done.** Live unlock / local `podman build` / buildah work
that is never cleaned becomes multi-GB disk dirt (pending ostree deploys, buildah
`*-working-container` Storage leftovers, full aipc/bazzite images in *user* podman).
Patterns and safe prune commands: **`docs/disk-layer-hygiene.md`** (also
claude-ops `LESSONS.md` L5).

## Why `/usr/lib/aipc/...` in the repo often isn't where the live file actually is

This is a bootc/ostree image: `/usr` on the running system is part of a read-only ostree
deployment, not writable at runtime. A module's `files/usr/lib/aipc/foo` path describes
where `foo` lands *inside the built image* — it does not mean `/usr/lib/aipc/foo` is
writable (or even the file systemd actually executes) on a machine that hasn't been
rebuilt since that module was added, or on any live hotfix workflow at all.

The pattern actually used on this machine: systemd units point `ExecStart=` at
`/etc/aipc/<name>` instead, and that's a real, writable, hand-maintained copy — check with:

```sh
systemctl cat <unit>.service | grep -i exec
```

If it says `/etc/aipc/...`, that's the live copy to patch, not the `/usr/lib/aipc/...` path
the module file lives at in the repo. If you don't know the unit name, find the file
directly:

```sh
find / -xdev -iname "<script-or-config-basename>" 2>/dev/null
```

(`-xdev` avoids wandering into `/sysroot/ostree/deploy/.../` — every historical ostree
deployment keeps its own full copy of `/usr`, which will otherwise flood the results with
irrelevant old versions.)

## The actual loop

1. Edit the repo file under `modules/<name>/files/...` — this is the file that must be
   correct, since it's what survives the next real image build.
2. Find the live path (see above) and diff it against the repo file before overwriting,
   so you know exactly what's about to change and aren't clobbering unrelated live drift:
   ```sh
   sudo diff modules/<name>/files/etc/aipc/foo /etc/aipc/foo
   ```
3. Copy it live and re-apply permissions/executable bit as needed:
   ```sh
   sudo cp modules/<name>/files/etc/aipc/foo /etc/aipc/foo
   sudo chmod +x /etc/aipc/foo   # if it's a script
   ```
4. Trigger whatever actually exercises the change — run the script directly, restart the
   unit, fire a `udevadm trigger`, hit the real endpoint — and hardware-verify the specific
   behavior, not just "it didn't error."
5. Commit the repo file only (never commit anything under `/etc/`). The live copy was a
   scratch artifact for verification; the repo is the only thing that has to be correct
   going forward, and the next `bootc switch` reapplies it properly through the real
   render pipeline.

## Concrete examples from this repo's history (see `docs/agent-log.md` for the full runs)

- `platform-profile-auto` / `platform-profile-idle-check` (module `system-unified-memory`):
  repo path is `files/usr/lib/aipc/...`, but the live units run
  `ExecStart=/etc/aipc/platform-profile-auto` / `/etc/aipc/platform-profile-idle-check` —
  found via `systemctl cat platform-profile-idle-check.service`.
- `models.yaml` (module `llm-models`): repo path
  `files/etc/aipc/models/models.yaml` matches the live path directly (`/etc/aipc/models/models.yaml`)
  since this one *is* meant to live under `/etc` even in a fresh image — always confirm
  with `diff` rather than assuming either way.
- `node.ini` (module `dev-distrobox-templates`): same — repo and live path line up at
  `/etc/aipc/distrobox/node.ini`, but the running distrobox container itself had to be
  patched separately (`distrobox-enter -n node -- ...`) since `init_hooks` in the `.ini`
  only fires when a container is first created, not on an already-running one.

## Secrets

See `docs/secrets-setup.md` for the full SOPS + age workflow (encrypting, decrypting,
rotating, recovery). Mechanism: secrets live encrypted in `secrets/*.yaml`; the AI PC's
runtime decryption key belongs at `/etc/aipc/age.key` (root-owned, `0600`, installed via
USB — never over network/chat, see CLAUDE.md §5); once present, decrypt a value with:

```sh
SOPS_AGE_KEY_FILE=/etc/aipc/age.key sudo sops --decrypt secrets/something.yaml
```

**Actual state of this machine, checked 2026-07-04**: this pipeline is not actually wired
up yet, and it's not (only) a missing-key problem. `aipc-decrypt-cloud-keys.service`
(from `secrets-sops`, which is supposed to populate cloud API keys at runtime — see
CLAUDE.md §8's build-time/runtime split) is `inactive`, condition unmet:
`ConditionPathExists=/etc/aipc/secrets/cloud-llm.yaml` — that encrypted secret file was
never created. `secrets/` in the repo only has the two `*.example` templates, no real
encrypted file was ever authored from them. Separately, `/etc/aipc/age.pub` (public key)
exists but `/etc/aipc/age.key` (private decryption key) does not either — the USB
transfer step in `docs/secrets-setup.md` §6 was never completed on this machine. Either
gap alone would block decryption; both are currently missing.

Net effect: `/etc/aipc/env.d/llm-litellm/cloud-keys.env` (what `litellm.container`'s
`EnvironmentFile=` actually reads) exists but is empty (0 bytes) — so the `main-cloud` /
`coder-cloud` / `thinking-cloud` / `gpt4o-cloud` / `gemini-cloud` aliases registered in
`llm-litellm`'s config are almost certainly non-functional right now. Don't assume a
cloud alias works without checking this file's actual size / `aipc-decrypt-cloud-keys`'s
status first. To actually fix this: author `secrets/cloud-llm.yaml` from the `.example`
template (`docs/secrets-setup.md` §3), transfer the private key to this machine (§6), then
re-run the `secrets-sops` module's post-install / the decrypt service.

Never write decrypted output anywhere under the repo, and never paste a decrypted value
into a commit, log, or chat message.
