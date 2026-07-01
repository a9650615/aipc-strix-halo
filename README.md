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
steps as a keyboard-operated menu. Use the Windows no-USB path only if a USB
installer is unavailable. The Strix Halo boot path still needs one hardware
boot test.

**Windows** (from Administrator PowerShell):

```powershell
Unblock-File .\Install-AIPC-Windows.ps1
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\Install-AIPC-Windows.ps1
```

The guided menu shows: install journey overview, basic settings checklist,
read-only preflight checks, staging with confirmation gates, and next steps
after staging.

**Linux** (after completing vanilla bazzite-dx install and booting installed system):

```sh
./install-aipc-linux.sh
```

The guided menu confirms you are on the installed system before invoking
`tools/bootstrap.sh`.

## Phase 0 status

Implements `system-unified-memory`, `system-base`, and `secrets-sops` modules.
Run `aipc doctor` on the AI PC after `bootc switch` to confirm all three are green.
