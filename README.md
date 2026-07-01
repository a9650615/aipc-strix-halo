# aipc_setup

Custom bootc image and Ansible playbook for an AMD Ryzen AI MAX+ 395 (Strix Halo) machine
running 128 GB unified DDR5X memory, gfx1151 iGPU, and XDNA 2 NPU.

## Design

See [`docs/architecture.md`](docs/architecture.md) for the full multi-phase design.

All capability proposals, implementation notes, and spec diffs live under [`openspec/`](openspec/).

## Repo layout

```
modules/          source of truth — one directory per capability module
targets/          generated artefacts (bootc Containerfile, Ansible playbook)
tools/            aipc CLI: render, doctor, secrets
secrets/          SOPS-encrypted secrets (age private key never in repo)
docs/             long-form documentation
.github/          CI workflows
```

## Quick start

```sh
# On the Mac, after age key generation (see docs/secrets-setup.md):
pip install -e tools
aipc render bootc --image-ref ghcr.io/<user>/aipc:test --build-date $(date +%F)
aipc render ansible
aipc doctor
```

## Install entrypoints

The guided entrypoints show the full install journey, prerequisites, and next
steps as a keyboard-operated menu. Two install paths are supported:

| Path | When to use |
|------|-------------|
| **USB SSD** (recommended) | You have a USB SSD or large USB stick available |
| **No-USB** | No USB drive available; stages installer from Windows directly |

The Strix Halo boot path still needs one hardware boot test for either path.

**Windows** (from Administrator PowerShell):

```powershell
Unblock-File .\Install-AIPC-Windows.ps1
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\Install-AIPC-Windows.ps1
```

The guided menu offers:

1. Install journey overview (both paths)
2. Basic settings checklist (BitLocker, Secure Boot, UEFI, disk space)
3. Read-only preflight checks
4. NO-USB staging (shrinks C:, creates AIPC_LIVE on internal disk, stages payload via rEFInd)
5. USB SSD staging (carves 35 GiB partition from USB SSD free space, stages payload, makes bootable)
6. Next steps after staging

**USB SSD path**: Select an external USB/ATA disk from the menu. The script creates
an `AIPC_LIVE` exFAT partition from the disk's free space without touching existing
data, downloads and verifies the Bazzite ISO, and stages the payload. Boot from the
USB SSD via F12/F1 one-time boot menu, then install Bazzite to the internal disk.

**Linux** (after completing vanilla bazzite-dx install and booting installed system):

```sh
./install-aipc-linux.sh
```

The guided menu confirms you are on the installed system before invoking
`tools/bootstrap.sh`. Includes a recovery/debug option with diagnostic commands
and log file location.

**Failure recovery**: Both scripts log all phases with timestamps. On failure, a
summary shows which phases completed, which failed, and specific recovery hints.
All phases are idempotent — retrying skips completed work. Windows logs to
`$env:ProgramData\aipc-windows-installer\install.log`; Linux logs to
`/var/log/aipc-bootstrap.log`.

## Phase 0 status

Implements `system-unified-memory`, `system-base`, and `secrets-sops` modules.
Run `aipc doctor` on the AI PC after `bootc switch` to confirm all three are green.
