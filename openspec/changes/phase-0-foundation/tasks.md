## 1. Repo Scaffolding (Mac)

- [x] 1.1 Create directory skeleton: `modules/`, `targets/{bootc,ansible}/`, `tools/`, `secrets/`, `docs/`, `.github/workflows/`
- [x] 1.2 Write `.gitignore` (excludes plaintext `secrets/*.yaml`, age keys, generated targets, Python caches, `.DS_Store`)
- [x] 1.3 Write MIT `LICENSE` with current year
- [x] 1.4 Write `.editorconfig` (2-space default, 4 for Python, tab for Makefile)
- [x] 1.5 Write `README.md` pointing readers to `docs/architecture.md` and `openspec/`
- [x] 1.6 `git init -b main`, first commit, `gh repo create aipc_setup --public --source=. --push`

## 2. Secrets Tooling (Mac)

- [x] 2.1 Install `sops` and `age` on the Mac via Homebrew
- [x] 2.2 Generate age keypair at `~/.config/aipc/age.key` (mode 0600); record the public key
- [x] 2.3 Write `secrets/.sops.yaml` with the user's age public key and an `encrypted_regex` that covers `*_key`, `*_token`, `*_secret`, `api_*`, `data`, `stringData`
- [x] 2.4 Create `secrets/example.example.yaml` with placeholder values and encrypt it in place with `sops`
- [x] 2.5 Confirm `sops --decrypt secrets/example.example.yaml` round-trips with `SOPS_AGE_KEY_FILE` pointing at the Mac key
- [x] 2.6 Write `docs/secrets-setup.md` (key location, USB transfer, rotation, recovery)
- [x] 2.7 Commit and push

## 3. Modules (Mac)

- [x] 3.1 Write `modules/system-unified-memory/`: `README.md`, `kargs.conf` (`amdgpu.gttsize=125000` + iommu), `env/hsa.sh`, `env/rocm.sh`, `modprobe.d/amdgpu.conf`, `packages.txt` (`rocm-smi`, `amd-smi`), `verify.sh` (GTT ≥ 120 GiB, rocm-smi sees device, HSA env set, NPU visible)
- [x] 3.2 Lint `system-unified-memory` with `shellcheck` and commit
- [x] 3.3 Write `modules/system-base/`: `README.md`, `packages.txt` (`bootc`, `btrfs-progs`, `snapper`, `age`, `sops`, `git-delta`, `jq`, `yq`, `httpie`, `ripgrep`, `fzf`), `files/etc/locale.conf`, `files/etc/aipc/branding.env` (placeholders), `post-install.sh` (localectl, timezone symlink, branding substitution from `$AIPC_*` env vars), `verify.sh` (tools present, timezone correct, branding substituted)
- [x] 3.4 Lint `system-base` and commit
- [x] 3.5 Write `modules/secrets-sops/`: `README.md`, empty `packages.txt`, `files/etc/aipc/sops.yaml`, `files/usr/local/lib/aipc/sops-env` (sources decrypted YAML into `SECRET_*` env vars; fails closed without `/etc/aipc/age.key`), `post-install.sh` (chmod helper), `verify.sh` (config present, helper executable, fails closed gracefully)
- [x] 3.6 Lint `secrets-sops` and commit

## 4. CLI (Mac, TDD)

- [x] 4.1 Write `tools/pyproject.toml` (Click + PyYAML + Rich; script entry `aipc = aipc_lib.cli:main`)
- [x] 4.2 Write failing test `tools/tests/test_modules.py` for `discover()` returning Module dataclasses with `packages` populated
- [x] 4.3 Implement `tools/aipc_lib/modules.py` until test passes
- [x] 4.4 Write failing test `tools/tests/test_render_bootc.py` asserting the emitted Containerfile has `FROM`, `RUN rpm-ostree install`, and `AIPC_IMAGE_REF`/`AIPC_BUILD_DATE` env lines
- [x] 4.5 Implement `tools/aipc_lib/render_bootc.py` until test passes
- [x] 4.6 Write failing test `tools/tests/test_render_ansible.py` asserting the emitted YAML has a `dnf` task with the package list
- [x] 4.7 Implement `tools/aipc_lib/render_ansible.py` until test passes
- [x] 4.8 Implement `tools/aipc_lib/doctor.py` and `tools/aipc_lib/secrets.py` (SOPS wrappers)
- [x] 4.9 Wire everything together in `tools/aipc_lib/cli.py` with Click subcommands `render bootc`, `render ansible`, `doctor`, `secrets {view,edit}`
- [x] 4.10 Smoke-test: `pip install -e tools`, run `aipc --help`, `aipc render bootc --image-ref test --build-date 2026-06-27`, confirm `targets/bootc/Containerfile.generated` is non-empty
- [x] 4.11 Commit and push

## 5. Bootstrap And CI (Mac)

- [x] 5.1 Write `tools/bootstrap.sh`: hardware probe (gfx1151 + XDNA + ≥ 120 GiB RAM), tag prompt (default `:stable`), age public-key prompt, GitHub user prompt, `bootc switch`, reboot prompt
- [x] 5.2 `shellcheck tools/bootstrap.sh` clean, `chmod +x`, commit
- [x] 5.3 Write `.github/workflows/ci.yml` (Python 3.12, install `tools`, run `pytest`, `ruff`, `shellcheck` over all `verify.sh` + `post-install.sh` + `env/*.sh` + `bootstrap.sh`, `yamllint -d relaxed`)
- [x] 5.4 Write `.github/workflows/build-image.yml` (`redhat-actions/buildah-build` → `redhat-actions/push-to-registry`, tags `:rolling` + `:YYYY-MM-DD` + optionally `:stable` on manual dispatch)
- [x] 5.5 `yamllint` workflows clean, commit, push
- [x] 5.6 Wait for first CI run; if build fails, inspect `targets/bootc/Containerfile.generated` from the run logs and patch the offending module

## 6. AI PC Migration (one-time)

- [ ] 6.1 On the AI PC running Windows 11: sign out of Microsoft account; back up BitLocker key from account.microsoft.com; back up Documents/Desktop/Downloads/Pictures/Videos to NAS or external drive; export browser bookmarks; record Steam library; capture `winget list > apps.txt`; record OEM product key via `Get-WmiObject`; disable BitLocker on system drive
- [ ] 6.2 Enter BIOS: enable EXPO/DOCP, enable Smart Access Memory, set UMA frame buffer to minimum, disable Secure Boot, set boot mode UEFI-only, set USB first in boot order, save and exit
- [ ] 6.3 On Mac: download latest `bazzite-dx-stable-amd64.iso` and its CHECKSUM; verify SHA-256
- [ ] 6.4 On Mac: write the ISO to a USB ≥ 8 GiB with `sudo dd if=... of=/dev/rdiskN bs=4m`; eject and label
- [ ] 6.5 On AI PC: boot the USB, choose "Erase entire disk and install", BTRFS layout default, hostname `aipc-strix`, timezone Asia/Taipei, locale en_US.UTF-8, create user account
- [ ] 6.6 First desktop login: confirm KDE Plasma loads; plug in Ethernet if Wi-Fi did not initialise

## 7. Hardware Verification (AI PC)

- [ ] 7.1 Confirm DDR speed is 8000 MT/s via `sudo dmidecode -t 17`
- [ ] 7.2 Confirm kernel ≥ 6.14 via `uname -r`; if older, `sudo bootc upgrade` and reboot
- [ ] 7.3 Confirm `dmesg | grep -i 'amdgpu.*gtt'` reports a value ≥ 122880 MB
- [ ] 7.4 Install `rocm-smi`, run `rocm-smi --showid` and `rocm-smi --showmeminfo vram`; confirm gfx1151 visible
- [ ] 7.5 Confirm `lspci | grep -iE 'signal processing|xdna'` returns the NPU
- [ ] 7.6 Smoke-test inference: install llama.cpp via Homebrew, pull Qwen2.5-7B-Q4 (small for first run), run with `-ngl 999`, confirm GPU memory used and tokens stream
- [ ] 7.7 Smoke-test STT: in a distrobox python:3.12 container, `pip install funasr soundfile`, load SenseVoiceSmall — first run downloads ~1 GB
- [ ] 7.8 Record outcomes in `docs/phase-0-verification-log.md`, commit and push from the Mac
- [ ] 7.9 If any item failed, open a new OpenSpec change describing the failure and the proposed fix; do NOT proceed until resolved

## 8. First Image And bootc switch

- [ ] 8.1 On the Mac: confirm the latest CI build is green and tags include today's date plus `:rolling`
- [ ] 8.2 On the AI PC: transfer the age public key (paste or USB; private key stays on Mac)
- [ ] 8.3 On the AI PC: run `tools/bootstrap.sh` with the published URL; choose `:rolling`; confirm GitHub user prompt; allow reboot
- [ ] 8.4 After reboot: `bootc status` shows the aipc image staged or booted
- [ ] 8.5 Install `tools/` from the cloned repo (`pip install --user -e ~/aipc_setup/tools`)
- [ ] 8.6 Run `aipc doctor`; expect three rows OK (with `secrets-sops` noting the age key is absent — expected)
- [ ] 8.7 On the Mac: `gh workflow run build-image.yml -f promote_stable=true` and confirm the `:stable` tag appears via `gh api`

## 9. Archive The Change

- [ ] 9.1 Run `openspec validate phase-0-foundation` and resolve any errors
- [ ] 9.2 Run `openspec archive phase-0-foundation` (this moves the change and updates `openspec/specs/system-foundation/spec.md` automatically)
- [ ] 9.3 Commit, push, and tag the milestone: `git tag -a phase-0-complete -m "Phase 0 system foundation complete"`
- [ ] 9.4 Open `openspec/changes/phase-1-ai-runtime` as the next change (out of scope for this plan)
