## Context

This is the first change in a multi-phase project (see `docs/architecture.md` for the full design across seven phases and 44 modules). The AI PC is AMD Ryzen AI MAX+ 395 (Strix Halo) with 128 GB DDR5X-8000 unified RAM, Radeon 8060S iGPU (gfx1151), and an XDNA 2 NPU. Strix Halo is 2025 silicon, so kernel ≥ 6.14, ROCm 7+, and the amd-xdna upstream driver are all required and all evolving. The user's authoring environment is a Mac; the AI PC is currently running pre-installed Windows 11 Home.

Stakeholders: one developer (the project owner). No other users in v1. The user is comfortable with Docker and bash but new to bootc, SOPS, age, and ROCm.

Constraints from `docs/architecture.md` (project-wide):

- Pure Linux, no Windows, no dual boot.
- `bazzite-dx` (Universal Blue, Fedora bootc base).
- `modules/` is the single source of truth; both `targets/bootc/Containerfile` and `targets/ansible/site.yml` are derived from it.
- Secrets: SOPS + age. The age private key is never in the repo or in CI.
- Model weights live outside the image (BTRFS subvolume bind-mount) — not Phase 0 work but the layout must not collide.

## Goals / Non-Goals

**Goals:**

- AI PC boots an aipc-branded image that passes `aipc doctor` for three modules.
- 128 GB RAM is exposed as a dynamic GTT pool; `dmesg` reports ≥ 120 GiB GTT.
- `rocm-smi` recognises gfx1151; `lspci` recognises XDNA.
- `tools/aipc render bootc` and `tools/aipc render ansible` produce buildable artefacts; both renderings of Phase 0 modules cause `aipc doctor` to print the same output on a fresh VM.
- CI publishes `ghcr.io/<user>/aipc:rolling`, `:YYYY-MM-DD`, and on demand `:stable`.
- `tools/bootstrap.sh` cleanly switches a vanilla bazzite-dx host to the aipc image; repeated runs are idempotent.

**Non-Goals:**

- Any LLM / voice / RAG / agent / gaming / dev tooling functionality.
- ROCm performance tuning beyond the GTT-size kargs.
- NPU userspace beyond presence detection (Lemonade SDK is Phase 1).
- A first-boot wizard with model pulls (stubbed only; populated in Phase 7).
- Re-enabling Secure Boot.
- An in-place dual boot with Windows.

## Decisions

**D1. Module shape is data-first, with one imperative escape hatch.**

Each module under `modules/` is a directory with `packages.txt`, `kargs.conf`, `modprobe.d/`, `files/`, `env/`, `post-install.sh`, `verify.sh`. The first four are consumed mechanically by both renderers (a renderer appends `packages.txt` to a single `dnf install`, copies `files/` into the image root, writes `kargs.conf` to `bootc kargs --append`, copies `env/*.sh` to `/etc/aipc/env.d/<module>/`). `post-install.sh` is the imperative escape hatch when none of the data inputs fits. `verify.sh` is the testable contract.

*Considered:* a single declarative YAML manifest per module. Rejected because shell already gives us idempotency primitives, and forcing every imperative bit through a DSL would just reinvent shell badly.

**D2. The Containerfile and Ansible playbook are generated, not hand-written.**

`tools/aipc render {bootc,ansible}` walks `modules/` and emits the artefact. The artefact lives at `targets/bootc/Containerfile.generated` and `targets/ansible/site.generated.yml`; both are `.gitignored`. CI regenerates them on every build. This prevents drift between the two renderings and between the `modules/` source and a stale committed artefact across 44 modules.

*Considered:* committing both files and updating by hand. Rejected — drift is inevitable at scale.

**D3. The CLI is Python 3 with Click.**

`tools/aipc` ships as a Python package under `tools/`. Click provides subcommands, help text, and shell completion for free. Python is already in the bazzite-dx base image and is one of the user's chosen languages (Q9a).

*Considered:* pure bash. Rejected — bash makes the renderer logic (file walking, YAML emission for Ansible, table output for `doctor`) fragile.

*Considered:* Go. Rejected — needless dependency for a single-machine CLI.

**D4. Secrets: SOPS + age, sample encrypted file lives in the repo.**

The age public key sits at `secrets/.sops.yaml`. An encrypted sample `secrets/example.example.yaml` is committed so `verify.sh` and CI can prove the decrypt path works on a host that has the key. The age **private** key is generated on the Mac at `~/.config/aipc/age.key` and never enters the repo or CI. On the AI PC, it is installed at `/etc/aipc/age.key` (mode 0400) either by the first-boot wizard (Phase 7) or by a one-shot USB transfer.

*Considered:* HashiCorp Vault. Rejected — overkill for one user; introduces a service requiring availability.

*Considered:* OS keyring. Rejected — not Git-friendly, no offline recovery.

**D5. CI uses `redhat-actions/buildah-build` against the rendered Containerfile.**

GitHub Actions free tier covers public repos with unlimited minutes; ghcr.io stores public images for free. Cache via BuildKit. The age private key never enters CI; the only secret is `GITHUB_TOKEN` (auto-issued, scoped to the repo).

*Considered:* self-hosted runner on the AI PC for faster builds. Rejected for v1 — the AI PC isn't built yet, and once it is, CI speed isn't a bottleneck.

**D6. Dual-tag publishing: `:rolling` always, `:YYYY-MM-DD` immutable, `:stable` manual promotion.**

Push to `main` and the weekly cron both update `:rolling` and add a new `:YYYY-MM-DD`. A `workflow_dispatch` with `promote_stable=true` re-tags the latest `:rolling` as `:stable`. The user picks per deployment.

**D7. Bootstrap.sh is interactive bash.**

Runs before Python is guaranteed sane on a vanilla bazzite-dx host (which it is, but defensive). Probes hardware before doing anything destructive. Idempotent: re-running with the same target tag is a no-op (bootc handles that).

## Risks / Trade-offs

- **Strix Halo Wi-Fi 7 firmware in older kernels** → bazzite-dx ISO might not boot networked. **Mitigation**: USB Ethernet adapter recommended on install day; instructions explicit in `docs/architecture.md §9.4`.
- **ROCm 7 + amd-xdna driver are evolving weekly** → today's pin can break next week. **Mitigation**: monthly review window built into the `:stable` promotion cadence; rollback via GRUB previous deployment.
- **Windows wipe is destructive** → user loses preinstalled OS, OEM key. **Mitigation**: `docs/architecture.md §9.1` pre-flight checklist; BitLocker recovery key and OEM product key recorded before wipe.
- **Secure Boot disabled** → reduced boot integrity. **Mitigation**: documented choice; future change to MOK-enrol bazzite-dx + aipc signing keys.
- **Age private key loss** → all encrypted secrets must be re-encrypted. **Mitigation**: key generation is one-shot on the Mac; the user copies the keyfile to USB and stores offline; later rotation procedure is documented in `docs/secrets-setup.md`.
- **CI build size** → ROCm packages alone are large; image may reach 5-10 GiB even at Phase 0. **Mitigation**: layer caching; rocm-smi/amd-smi only (not the full ROCm SDK) at Phase 0 — full SDK comes in Phase 1.
- **`aipc doctor` over-reporting OK on Phase 0** → `secrets-sops` reports OK without the age key present because the key is not installed in image. **Mitigation**: `verify.sh` distinguishes "key absent (expected)" from "config broken" with separate exit codes.

## Migration Plan

The only "migration" is Windows 11 → vanilla bazzite-dx → aipc image, executed once on the AI PC. Sequenced in `tasks.md` group 4. Rollback at each layer:

- Pre-bazzite-install: BitLocker key + OEM key noted; reinstall Windows via Microsoft Recovery Media if needed.
- Post-bazzite-install, pre-bootc-switch: vanilla bazzite-dx is the rollback target; re-flash USB if anything corrupts.
- Post-bootc-switch: GRUB shows two deployments; previous (`bazzite-dx`) bootable.
- Worst case: re-flash USB, lose nothing in `/var/home` or `/var/lib/aipc-models` if the BTRFS layout is preserved (procedure in `docs/recovery.md`, written in this change).

## Open Questions

- **GTT-size exact value**: spec says ≥ 120 GiB; we set `amdgpu.gttsize=125000`. Optimal value to be measured during hardware verification (`tasks.md` group 4). If `dmesg` reports a value other than ~120 GiB, revisit before committing the karg pin.
- **Whether `amdgpu.sg_display=1` is required on first-boot KMS**: hardware verification will tell us; if it causes display issues, drop it from `kargs.conf` and document why.
- **CI runner choice for `redhat-actions/buildah-build`**: Ubuntu 24.04 (default GitHub-hosted) vs Fedora container. Start with Ubuntu, switch if `bootc` tooling needs Fedora packages we can't apt-get.
