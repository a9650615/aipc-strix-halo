## Why

A brand-new AMD Ryzen AI MAX+ 395 machine ships with Windows 11 Home, and Strix Halo is too new to assume any Linux-side behaviour from training data. Before any of the AI capabilities described in `docs/architecture.md` can be layered, three foundations have to be real: the hardware boots Linux with iGPU/NPU/unified-memory functional, the repo can render itself into both a bootc image and an Ansible playbook from the same `modules/` source, and CI publishes those images to ghcr.io under the dual-tag scheme. Until all three exist, every later phase is blocked.

## What Changes

- Migrate the host off Windows 11 onto vanilla bazzite-dx (one-time, documented checklist).
- Create the three Phase 0 modules (`system-unified-memory`, `system-base`, `secrets-sops`) under `modules/`.
- Add the `tools/aipc` Python CLI with `render bootc`, `render ansible`, `doctor`, `secrets {view,edit}` subcommands; cover with pytest.
- Add `tools/bootstrap.sh` to switch a vanilla bazzite-dx host onto the published aipc image.
- Add GitHub Actions workflows: `ci.yml` (lint + tests) and `build-image.yml` (build + push `:rolling`, `:YYYY-MM-DD`, and optionally `:stable`).
- Add SOPS + age secrets workflow with a sample encrypted file under `secrets/`.
- Record Phase 0 hardware verification results in `docs/phase-0-verification-log.md`.
- Run `bootc switch` on the AI PC to land on the first published `:rolling` image.

This change does **not** introduce any AI runtime, voice, RAG, agent, gaming, or dev capability — those are separate later changes.

## Capabilities

### New Capabilities

- `system-foundation`: kernel tuning for the 128 GB unified memory pool; ROCm 7 + amd-xdna recognition; base packages (locale, timezone, BTRFS, snapper, SOPS, age, CLI utilities); SOPS-encrypted runtime secret loading; the repo's dual rendering pipeline (bootc Containerfile + Ansible playbook from a single `modules/` source); image distribution via ghcr.io with `:rolling`, `:stable`, and `:YYYY-MM-DD` tags; bootstrap from vanilla bazzite-dx; `aipc doctor` health check.

### Modified Capabilities

None. No prior specs exist.

## Impact

- **Hardware**: The user's AI PC is wiped of Windows 11. There is no in-place dual boot in v1.
- **External services**: GitHub Actions (free tier on a public repo) and ghcr.io (free for public images) are now load-bearing.
- **Secrets**: An age private key on the user's Mac becomes the trust root; loss requires rotating every encrypted value.
- **Foundation for all later phases**: every subsequent OpenSpec change (Phase 1 AI runtime onwards) depends on the `aipc doctor`-green state this change produces.
- **Documentation**: `docs/architecture.md` (the full multi-phase design) is the long-form reference this change implements the first slice of.
