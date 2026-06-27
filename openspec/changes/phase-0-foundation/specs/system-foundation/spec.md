## ADDED Requirements

### Requirement: Unified Memory Pool Exposed To iGPU

The kernel SHALL boot with parameters that expose ≥ 95 % of system RAM as dynamic GPU memory (GTT), targeting gfx1151 via HSA userspace overrides.

#### Scenario: GTT reports at least 120 GiB

- **WHEN** the AI PC boots the aipc image and the project owner runs `dmesg | grep -i 'amdgpu.*gtt'`
- **THEN** at least one line reports `GTT size: NNNNNN MB` with NNNNNN ≥ 122880 (120 GiB)

#### Scenario: ROCm recognises the iGPU

- **WHEN** the project owner runs `rocm-smi --showid`
- **THEN** the command exits 0 and prints a device whose name or ID identifies gfx1151 / Radeon 8060S

#### Scenario: HSA override exported system-wide

- **WHEN** a login shell sources `/etc/aipc/env.d/system-unified-memory/hsa.sh`
- **THEN** `HSA_OVERRIDE_GFX_VERSION=11.5.1` is set in that shell's environment

#### Scenario: NPU visible via lspci

- **WHEN** the project owner runs `lspci | grep -i 'signal processing\|xdna'`
- **THEN** at least one line referencing XDNA or "Signal Processing Controller" is returned

### Requirement: Base Packages, Locale, Timezone, Branding

The aipc image SHALL ship with base packages, locale (en_US.UTF-8 + zh_TW.UTF-8), timezone Asia/Taipei, and a `/etc/aipc/branding.env` reporting `IMAGE_REF` and `BUILD_DATE`.

#### Scenario: Required tools present

- **WHEN** the project owner runs `command -v jq yq sops age btrfs snapper rg fzf delta` after booting the image
- **THEN** each command succeeds, indicating the binary is on `$PATH`

#### Scenario: Timezone is Asia/Taipei

- **WHEN** the project owner runs `readlink /etc/localtime`
- **THEN** the symlink target ends in `Asia/Taipei`

#### Scenario: Branding stamped with real values

- **WHEN** the project owner runs `cat /etc/aipc/branding.env`
- **THEN** `IMAGE_REF` is a real ghcr.io reference (not the literal string `PLACEHOLDER`) and `BUILD_DATE` is an ISO date

### Requirement: SOPS-Based Secrets Workflow

The aipc image SHALL provide a system-wide SOPS configuration at `/etc/aipc/sops.yaml` and a sourceable helper at `/usr/local/lib/aipc/sops-env` that fails closed when the age private key at `/etc/aipc/age.key` is absent.

#### Scenario: SOPS configuration present

- **WHEN** the project owner runs `test -r /etc/aipc/sops.yaml`
- **THEN** the command exits 0

#### Scenario: Helper is executable

- **WHEN** the project owner runs `test -x /usr/local/lib/aipc/sops-env`
- **THEN** the command exits 0

#### Scenario: Helper fails closed without age key

- **WHEN** the project owner sources the helper while `/etc/aipc/age.key` does not exist
- **THEN** the helper writes a message to stderr referencing `aipc secrets install-key` and exits non-zero without writing decrypted output

#### Scenario: Helper decrypts when age key present

- **WHEN** the project owner installs a valid age key at `/etc/aipc/age.key` (mode 0400) and sources the helper against a SOPS-encrypted YAML
- **THEN** the matching `SECRET_*` environment variables are exported and equal to the plaintext values

### Requirement: Dual Rendering From Modules

The repo SHALL render the same `modules/` source into both a bootc Containerfile and an Ansible playbook such that both renderings produce identical `aipc doctor` output on a fresh Fedora-based host.

#### Scenario: `aipc render bootc` succeeds

- **WHEN** the project owner runs `aipc render bootc --image-ref ghcr.io/example/aipc:test --build-date 2026-06-27`
- **THEN** the command exits 0 and writes a non-empty file to `targets/bootc/Containerfile.generated` that contains a `FROM` directive and at least one `rpm-ostree install` line

#### Scenario: `aipc render ansible` succeeds and lints

- **WHEN** the project owner runs `aipc render ansible` followed by `ansible-lint targets/ansible/site.generated.yml`
- **THEN** both commands exit 0

#### Scenario: Renderings agree on doctor output

- **WHEN** an OpenSpec-validated Phase 0 image (built via the bootc render) and a clean Fedora VM provisioned via the Ansible render both run `aipc doctor` on identical hardware
- **THEN** the two `aipc doctor` outputs report the same module count and the same per-module OK/FAIL status

### Requirement: Image Distribution To ghcr.io

CI SHALL build the aipc image and push three tags to `ghcr.io/<user>/aipc`: `:rolling` (every successful build), `:YYYY-MM-DD` (every successful build, immutable), and `:stable` (only on manual `workflow_dispatch` with `promote_stable=true`).

#### Scenario: Push to main produces rolling tag

- **WHEN** a commit lands on `main` and the `build-image.yml` workflow finishes successfully
- **THEN** `ghcr.io/<user>/aipc:rolling` resolves to the new digest and a tag matching today's UTC date is also present

#### Scenario: Stable promotion is manual

- **WHEN** the project owner runs `gh workflow run build-image.yml -f promote_stable=true` and the workflow finishes successfully
- **THEN** `ghcr.io/<user>/aipc:stable` resolves to that build's digest

#### Scenario: No plaintext age private key in CI

- **WHEN** the workflow runs to completion
- **THEN** the rendered CI logs and the resulting image contain no plaintext value of the age private key

### Requirement: Bootstrap From Vanilla bazzite-dx

`tools/bootstrap.sh` SHALL probe hardware, collect the user's age public key, and `bootc switch` a vanilla bazzite-dx host to the chosen aipc tag, with a reboot prompt.

#### Scenario: Aborts on wrong hardware

- **WHEN** `tools/bootstrap.sh` runs on a host whose iGPU is not Strix Halo or whose RAM is < 120 GiB
- **THEN** it writes a one-line diagnostic to stderr and exits non-zero before invoking `bootc switch`

#### Scenario: Successful first run

- **WHEN** `tools/bootstrap.sh` runs on a fresh vanilla bazzite-dx host with valid input
- **THEN** `/etc/aipc/age.pub` is written, `bootc switch ghcr.io/<user>/aipc:<tag>` is invoked, and the host reboots into the aipc image

#### Scenario: Idempotent re-run

- **WHEN** `tools/bootstrap.sh` runs a second time with the same chosen tag on a host already running that tag
- **THEN** the script exits 0 without invoking `bootc switch` again

### Requirement: Health Check Reports Per Module

The `aipc doctor` command SHALL execute every discovered module's `verify.sh` and report a per-module OK/FAIL status with a one-line diagnosis on failure.

#### Scenario: Green on healthy image

- **WHEN** `aipc doctor` runs on a host where every module's `verify.sh` exits 0
- **THEN** the printed table shows OK for every module and the process exits 0

#### Scenario: Pinpoint failure

- **WHEN** the project owner intentionally renames `/etc/aipc/branding.env` to break `system-base` and runs `aipc doctor`
- **THEN** the table shows FAIL only for `system-base`, the diagnosis references the missing `/etc/aipc/branding.env`, and the process exits non-zero
