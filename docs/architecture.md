# AI PC Setup

A reproducible, modular setup for transforming an **AMD Ryzen AI MAX+ 395 (Strix Halo)** workstation into a local-first AI assistant, RAG-equipped knowledge worker, agentic operator, gaming console, and developer rig — all on a single immutable Linux base, defined declaratively.

---

## 1. Hardware

| Component | Spec |
|---|---|
| CPU | AMD Ryzen AI MAX+ 395 (Strix Halo APU, Zen 5) |
| iGPU | Radeon 8060S, 40 CUs, gfx1151 |
| NPU | XDNA 2, ~50 TOPS |
| RAM | 128 GB DDR5X-8000 (unified, shared across CPU/iGPU/NPU) |
| Storage | NVMe (BTRFS planned for system + model subvolumes) |
| Display | Single monitor at v1; satellite/headless extensible |
| Audio | USB / Bluetooth mic + speaker/headset |

The 128 GB unified memory is the defining capability — large LLMs (70B-class Q4) can coexist with multiple inference daemons and desktop workload without VRAM management gymnastics.

---

## 2. Goals

1. **Always-on local AI assistant** — voice-callable wake word → STT → LLM → TTS pipeline that runs 24/7 on NPU/iGPU.
2. **Persistent intelligence** — RAG over personal documents, code, browser, screen, and email/calendar; long-term memory of facts, preferences, and conversations via mem0.
3. **Capable agent layer** — multi-agent orchestration (code/shell, browser, screen-control, file/calendar) coordinated by LangGraph, with broad tool surface via MCP.
4. **First-class gaming** — SteamOS-equivalent gamescope session, AI overlay callable by voice for game strategy assistance.
5. **Developer rig** — VSCode + Zed + Neovim; Node + Python distrobox; Continue.dev + Cline + Aider + Goose + Claude Code, all sharing one LiteLLM gateway, giving a Claude-Code-equivalent local experience.
6. **Reproducible installer** — entire system declared in this repo; rebuild from scratch in under an hour; identical on every install.
7. **Modular (Lego-style)** — each capability is an independent module; the base system is immutable and cannot be corrupted by customisation.

---

## 3. Non-Goals

| Excluded | Reason |
|---|---|
| Windows / dual boot | User chose pure Linux explicitly |
| SteamOS upstream | Strix Halo not officially supported; bazzite-dx covers the same UX |
| Cursor / closed-source IDE-bundled AI | Not local-first |
| Obsidian / Notion sync (v1) | User did not select; OpenSpec change can add later |
| Discord / Slack / Telegram chat ingest (v1) | Same as above |
| Multi-user host | Single-user workstation |
| iOS dev | Not possible on Linux |
| Mobile / tablet voice satellites (v1) | Pipecat transport keeps the path open for v2 |

---

## 4. Architecture Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| Q1 | OS strategy | Pure Linux, no Windows |
| Q1.5 | Migration from preinstalled Win11 Home | Full wipe; documented pre-flight + BIOS prep in §9.1-9.2 |
| Q2 | Distribution | bazzite-dx (Universal Blue, Fedora bootc base) |
| Q2.5 | Module rendering | `modules/` shared source; `targets/bootc/` (primary) + `targets/ansible/` (fallback) |
| Q3 | LLM stack | LiteLLM gateway + Lemonade SDK (NPU + iGPU/Vulkan, primary local backend as of 2026-07-05) + Ollama (iGPU, installed/enabled but idle — no aliases registered) + vLLM (on-demand) |
| Q4 | Voice pipeline | Pipecat orchestrator; openWakeWord (NPU); Silero VAD; SenseVoice (short Chinese) + Paraformer-zh-streaming (long/streaming Chinese); CosyVoice 2 (Chinese TTS) + Kokoro/Piper (English/fallback) |
| Q5 | RAG + Memory | mem0 + Qdrant + Postgres/pgvector + bge-m3 embeddings + bge-reranker-v2-m3; ingest desktop docs, code, browser history+bookmarks, screen+OCR, email+calendar |
| Q6 | Agent framework | LangGraph orchestrator + Open Interpreter (code/shell) + browser-use (web) + Computer-Use (Qwen2-VL + xdotool) + MCP gateway; main brain Hermes-3-70B or Qwen2.5-72B-Instruct (Phase 0 bake-off) |
| Q7 | Gaming | gamescope session + voice-callable AI overlay (Bluetooth headset primary) + smart-prompt strategy RAG (ask once on game launch) + shared mem0 with desktop |
| Q8a | Install | Vanilla bazzite-dx ISO + `bootstrap.sh` `bootc switch` to our image |
| Q8b | Secrets | SOPS + age, encrypted YAML in repo, private key on USB/YubiKey |
| Q8c | Model weights | Independent BTRFS subvolume at `/var/lib/aipc-models`, bind-mounted into containers; not baked into image |
| Q8d | First-boot | Interactive CLI wizard (`aipc init`), supports `--non-interactive --config foo.yaml` for unattended |
| Q8e | Updates | Dual-tag: `:rolling` (weekly upstream sync) + `:stable` (monthly cut); user selects per deployment |
| Q9a | Dev languages | Node + Python distrobox templates at v1 (Go/Rust/Android via OpenSpec change later) |
| Q9b | Editors | VSCode + Zed + Neovim (LazyVim) |
| Q9c | AI coding | Continue.dev (autocomplete) + Cline (VSCode agentic) + Aider (terminal pair) + Goose (Claude-Code-like CLI) + Claude Code (Anthropic CLI, user's API key) |

---

## 5. System Topology

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Hardware: Strix Halo + 128GB unified RAM                                 │
├──────────────────────────────────────────────────────────────────────────┤
│ Fedora bootc kernel (kargs tuned for unified memory + XDNA + ROCm)       │
├──────────────────────────────────────────────────────────────────────────┤
│ bazzite-dx base image (read-only)                                        │
├──────────────────────────────────────────────────────────────────────────┤
│ aipc image layer (this repo, built via Containerfile, hosted on ghcr.io) │
│ - Phase 0 system tuning, ROCm 7, XDNA driver, Lemonade SDK               │
│ - Phase 1-6 runtime daemons baked as Podman quadlets                     │
│ - SOPS-encrypted secret blobs                                            │
├──────────────────────────────────────────────────────────────────────────┤
│ Distrobox containers (mutable dev envs: Node, Python, general)           │
├──────────────────────────────────────────────────────────────────────────┤
│ Bind-mounted state                                                       │
│ - /var/lib/aipc-models    (BTRFS subvol, model weights)                  │
│ - /var/lib/aipc-state     (BTRFS subvol, mem0 / qdrant / postgres data)  │
│ - /home/$USER             (BTRFS subvol, user data)                      │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Flow (Voice + Memory + Agent Loop)

```
microphone
   │
   ▼
openWakeWord  (NPU, always-on, < 2W)
   │  wake event
   ▼
Silero VAD   (NPU)
   │  speech segment
   ▼
SenseVoice / Paraformer-zh-streaming  (iGPU)
   │  text
   ▼
Pipecat handler
   │
   ├─→ mem0.search(user_id, recent_episodes)
   ├─→ RAG.search(query)  → Qdrant + reranker
   │
   ▼
LiteLLM gateway
   │ routed by model name
   ├─→ Lemonade (NPU + iGPU/Vulkan) : resident-small, coder-agentic, ornith-35b (primary local backend)
   ├─→ Ollama (iGPU)     : installed/enabled, currently idle — no aliases registered
   └─→ vLLM (iGPU)       : high-throughput / vision (on demand)
   │  response stream
   ▼
LangGraph agent (if tool use required)
   ├─→ Open Interpreter (code/shell)
   ├─→ browser-use      (web)
   ├─→ Computer-Use     (screen)
   ├─→ MCP gateway      (100+ tools)
   └─→ File / Calendar / Search tools
   │  final reply
   ▼
CosyVoice 2 / Kokoro / Piper  (iGPU/CPU)
   │
   ▼
speaker / Bluetooth headset

Side-effects:
   • mem0.add(conversation) — auto-extract facts and episodes
   • RAG.ingest(any new artefacts referenced)
```

---

## 7. Module Inventory (46 modules across 7 phases)

Module structure (each module follows the same shape):

```
modules/<name>/
├── README.md            # what / how / depends-on
├── packages.txt         # rpm-ostree / dnf packages (consumed by both targets)
├── files/               # tracked file overlays
├── env/                 # environment vars (sourced at boot)
├── quadlet/             # Podman quadlet units (services)
├── kargs.conf           # kernel cmdline additions (Phase 0 only)
├── modprobe.d/          # kernel module params (Phase 0 only)
├── post-install.sh      # idempotent setup (image build time)
└── verify.sh            # health check, used by `aipc doctor`
```

### Phase 0 — System Foundation

| Module | Purpose |
|---|---|
| `system-unified-memory` | UMA min, `amdgpu.gttsize`, HSA env, "Mac-like" memory pool |
| `system-base` | Base packages, locale, timezone, networking, firewalld profile |
| `secrets-sops` | SOPS + age installation, key locations |

### Phase 1 — AI Runtime

| Module | Purpose |
|---|---|
| `ai-rocm` | ROCm 7 stack (HIP runtime, rocm-smi, etc.) |
| `ai-xdna` | amd-xdna driver + Lemonade SDK userspace |
| `llm-litellm` | Gateway daemon + router config |
| `llm-lemonade` | NPU inference service (small / routing models) |
| `llm-ollama` | iGPU inference service — installed/enabled but idle as of 2026-07-05 (no aliases registered; Lemonade is the primary local backend, see `llm-lemonade`) |
| `llm-vllm` | High-throughput / vision inference (on-demand) |
| `llm-models` | `models.yaml` manifest + `aipc models sync` |

### Phase 2 — Knowledge & Memory

| Module | Purpose |
|---|---|
| `db-postgres` | Postgres + pgvector quadlet |
| `db-qdrant` | Qdrant quadlet |
| `rag-embedder` | bge-m3 + reranker service |
| `rag-ingest` | Watcher daemons: desktop docs, code repos, browser, screen+OCR, email+calendar |
| `memory-mem0` | mem0 server, LiteLLM integration |

### Phase 3 — Voice

| Module | Purpose |
|---|---|
| `voice-pipecat` | Pipecat orchestrator + pipeline config |
| `voice-wake` | openWakeWord (NPU, ONNX) + wake-word training docs |
| `voice-stt-sensevoice` | SenseVoice-Small service (short utterance) |
| `voice-stt-paraformer` | Paraformer-zh-streaming service (long / dictation) |
| `voice-tts-cosyvoice` | CosyVoice 2 service (Chinese TTS) |
| `voice-tts-kokoro` | Kokoro / Piper service (English / fallback) |

Voice pipeline details and current staged verification status live in `docs/voice-pipeline.md`.

### Phase 4 — Agent

| Module | Purpose |
|---|---|
| `agent-orchestrator` | LangGraph daemon + graph definitions |
| `agent-code-shell` | Open Interpreter wrapper |
| `agent-browser` | browser-use + Playwright |
| `agent-screen-control` | Qwen2-VL + xdotool/ydotool + window blacklist + session gate |
| `agent-tools-files` | File system tools |
| `agent-tools-calendar` | Calendar + Email (CalDAV / IMAP) tools |
| `agent-tools-search` | SearXNG self-host + search tool |
| `agent-mcp-gateway` | MCP server registry + gateway daemon |
| `agent-gate` | Permission gate: grant/revoke/check/audit for risky actions (UNIX-socket RPC, `aipc-agent-gate.service`) |

### Phase 5 — Gaming

| Module | Purpose |
|---|---|
| `gaming-base` | gamescope session, controller mapping, HUD presets |
| `gaming-ai-overlay` | In-game voice overlay (wake word stays active) + floating HUD |
| `game-strategy-rag` | Smart-prompt strategy ingest (Fextralife / wikis / Chinese wikis) |

### Phase 6 — Dev

| Module | Purpose |
|---|---|
| `dev-cli` | fish/gh/zoxide/bat/eza + fonts (build-time); starship/lazygit/ghostty/mise/atuin documented as manual installs |
| `dev-editors` | Zed (primary) + VSCode (secondary), runtime Flatpak installs + fonts |
| `dev-distrobox-templates` | Node, Python distrobox-assemble templates (INI syntax) |
| `dev-ai-continue` | Continue.dev → LiteLLM config |
| `dev-ai-cline` | Cline (VSCode) → LiteLLM config |
| `dev-ai-aider` | Aider → LiteLLM config |
| `dev-ai-goose` | Goose → LiteLLM + MCP config |
| `dev-ai-claude-code` | Claude Code CLI |
| `dev-ai-opencode` | OpenCode CLI → LiteLLM config |
| `ccs` | CCS — multi-provider Claude Code/Codex/Droid switcher, `aipc` profile → LiteLLM |
| `dev-ai-mcp-dev-servers` | GitHub / FS / Playwright MCP servers (disabled, blocked on phase-4-agent) |

### Phase 7 — Ops

| Module | Purpose |
|---|---|
| `ops-backup` | BTRFS snapshot policy (snapper) for mem0 / Qdrant / Postgres / `/home` |
| `ops-doctor` | `aipc doctor` health check (rocm-smi, xdna-smi, service status, model presence) |
| `ops-firstboot` | First-boot wizard (`aipc init`) — name, voice, models, Steam, API keys |

---

## 8. Build & Deploy

```
┌─────────────────────────┐
│  modules/  (source)     │  ← single source of truth
└──────┬──────────┬───────┘
       │          │
       ▼          ▼
┌──────────┐  ┌──────────┐
│ targets/ │  │ targets/ │
│ bootc/   │  │ ansible/ │
│ Container│  │ site.yml │
│ file     │  │          │
└────┬─────┘  └─────┬────┘
     │              │
     ▼              ▼
 GitHub Actions   Ansible (manual)
     │
     ▼
ghcr.io/<user>/aipc:rolling
ghcr.io/<user>/aipc:stable
ghcr.io/<user>/aipc:YYYY-MM-DD
```

CI tags:

| Tag | Refresh | Promotion |
|---|---|---|
| `:rolling` | Weekly (rebases on upstream bazzite-dx) | Automatic |
| `:stable` | Monthly | Manual: re-tag the latest rolling that has passed `aipc doctor` |
| `:YYYY-MM-DD` | Each successful build | Immutable, for rollback |

---

## 9. Install Flow

> No USB stick available? See **§9 Alt: Windows-Direct Install (No USB Required)** below for a path installed entirely from the running Windows host.

The machine ships from the vendor with **Windows 11 Home preinstalled**. Migration is one-way: Windows is wiped. The flow below assumes the user has another machine (e.g., a Mac) available to prepare the USB installer.

> **The very first time** this project is built (by the project owner), the published aipc image does not yet exist. In that case: complete §9.1 through §9.4 to land on vanilla bazzite-dx, then jump to §10 Phase 0 Hardware Verification. Only after the first :rolling tag is pushed to ghcr.io do §9.5 and §9.6 become applicable. Subsequent installs (rebuilds, friends, replacements) run §9.1 → §9.6 end to end.

### 9.1 Pre-flight on Windows (one-time, before wipe)

```
[ ] Sign out of Microsoft account (Settings → Accounts → Your info → Sign out)
[ ] Back up BitLocker recovery key from account.microsoft.com/devices (insurance)
[ ] Back up any Windows-only data to external drive or NAS
    - /Users/<you>/Documents, Desktop, Downloads, Pictures, Videos
    - Browser bookmarks export (.html) and password CSV if not in cloud
    - Steam library list (so we know what to re-download on Linux)
    - Save list of installed apps (`winget list > apps.txt` in PowerShell)
[ ] Record Windows OEM product key (in case of future warranty support)
    - PowerShell: (Get-WmiObject -query 'select * from SoftwareLicensingService').OA3xOriginalProductKey
[ ] Note current BIOS version and firmware build
[ ] Confirm the machine has no vendor-locked recovery partition that wipes silently
[ ] Disable BitLocker on the system drive (Settings → Privacy → Device encryption → Off)
    Otherwise the bazzite installer cannot resize / wipe encrypted partitions cleanly.
```

### 9.2 BIOS Preparation (one-time)

Reboot to BIOS (Del / F2 at POST). Apply once and save:

```
[ ] CPU / RAM:
      - Enable EXPO / DOCP profile (DDR5X-8000 official speed)
      - Enable Smart Access Memory (Resizable BAR)
[ ] Integrated Graphics:
      - UMA Frame Buffer Size: minimum (512 MB or 1 GB)
        (Strix Halo treats the rest of the 128 GB pool as dynamic GTT)
[ ] Security:
      - Secure Boot: Disabled
        (bazzite-dx supports Secure Boot with a one-time MOK enrolment; for v1
         we recommend Disabled and revisit in an OpenSpec change later)
      - TPM: enabled (left untouched)
[ ] Boot:
      - Boot mode: UEFI only (no CSM / Legacy)
      - Set USB stick first in boot priority
[ ] Save and exit.
```

### 9.3 USB Installer Creation (from macOS, since the user is on Mac)

```
# On the Mac:
1. Download vanilla bazzite-dx ISO:
       https://download.bazzite.gg/bazzite-stable-amd64.iso
2. Verify SHA-256 against the .CHECKSUM file from bazzite.gg.
3. Identify the USB stick (≥ 16 GB; the ISO is ~7.9 GB, an "8 GB" stick may not fit):
       diskutil list
4. Unmount (NOT eject):
       diskutil unmountDisk /dev/diskN
5. Write the ISO:
       sudo dd if=/path/to/bazzite-dx.iso of=/dev/rdiskN bs=4m status=progress
6. Eject:
       diskutil eject /dev/diskN
```

(Alternative: balenaEtcher for a guided GUI flow. Avoid Rufus — Windows only and rewrites bootloader; the raw `dd` write is what bazzite expects.)

### 9.4 Bazzite-DX Install on the AI PC

```
[ ] Insert USB, power on, hit F12 / F11 for one-time boot menu
[ ] Select the USB → bazzite installer boots
[ ] Choose: "Erase entire disk and install" → bazzite layout (BTRFS, /home and /var-home subvolumes)
[ ] Set hostname (e.g., `aipc-strix`), timezone, locale, username
[ ] Wait ~10 minutes
[ ] Reboot, remove USB
[ ] First boot into vanilla bazzite-dx desktop
```

⚠ **Strix Halo Wi-Fi 7 + Bluetooth firmware** may need network at install for full functionality. Bazzite-dx ships kernel ≥ 6.14 which has the firmware; verify in §9.6. If Wi-Fi fails to initialise on first boot, plug in Ethernet (or USB-Ethernet) for the bootstrap step.

### §9 Alt: Windows-Direct Install (No USB Required)

**This section describes an alternative install path that boots the bazzite-dx installer directly from the machine's own NVMe via an EFI boot manager dropped into the ESP from Windows. Use this path ONLY if you cannot acquire a USB stick.**

The USB path (§9.3–§9.4) remains the primary recommendation: faster, lower-risk, with years of community documentation. The Windows-direct path is for users who cannot acquire a USB stick but who have a working Windows 11 install, UEFI firmware, and ≥150 GB of unallocated NVMe space.

**Prerequisites:**
- Windows 11 installed and booting
- UEFI firmware (not Legacy/CSM)
- ≥150 GB of unallocated NVMe space
- No USB stick available

**Key design decisions:**

| Decision | Choice | Rationale |
|---|---|---|
| **D1: EFI boot manager** | rEFInd 0.14+ | Ships Windows-side installer (`refind-install.bat`), registers via `bcdedit`/NVRAM, stable ISO chainload, mature project |
| **D2: ISO boot method** | Extract vmlinuz + initrd + LiveOS | Mount ISO, copy kernel/initrd to ESP, LiveOS to exFAT partition. More reliable than chainloading raw ISO across firmware variants |
| **D3: Disk layout** | 30 GB exFAT AIPC_LIVE partition + 120 GB unallocated | LiveOS squashfs can exceed FAT32's 4 GiB limit. Two-step shrink: Windows → 150 GB unallocated → carve 30 GB for AIPC_LIVE, leave 120 GB for bazzite |
| **D4: Windows handling** | Dual-boot 30 days, then wipe | Wiping same-session is high-risk (no rollback if Linux fails). After 30-day soak (`aipc doctor` green), user manually removes Windows + 30 GB partition |
| **D5: Recovery without USB** | WinRE + System Image Backup | WinRE lives on hidden Windows partition, reachable via Shift+Restart. Pre-flight requires System Image Backup to NAS/OneDrive/second internal drive (NOT USB) |
| **D6: Secure Boot** | Disabled (unchanged from §9.2) | rEFInd supports Secure Boot via shim, but MOK key enrolment is advanced setup. Defer to later OpenSpec change |
| **D7: Default status** | Opt-in alternative, not default | USB path is faster and lower-risk. Windows-direct is fallback when USB unavailable. |

**Cross-references:**
- §9.1 Pre-flight on Windows (unchanged, plus mandatory System Image Backup)
- §9.2 BIOS Preparation (unchanged — no new BIOS settings for this path)
- §9.5 Bootstrap to the aipc Image (converges on same vanilla bazzite-dx state)
- §9.6 First-boot Wizard (unchanged — same `aipc init` flow)
- §9.7 Rollback Insurance (same GRUB previous deployment mechanism)
- §9.8 Time Estimate (same ~2.5 hours total)

**Runbook:** See `docs/install-windows-direct-runbook.md` for step-by-step walkthrough (~30 numbered steps) with screenshot placeholders grouped into Pre-flight, EFI loader setup, Disk partitioning, Boot flow, and Post-install cleanup (30-day deferred).

**Recovery path:** WinRE (Shift+Restart → Troubleshoot → Advanced → System Image Recovery) restores from the pre-flight System Image Backup. No USB stick required at any point. WinRE lives on a hidden Windows partition and boots independently of the main bootloader.

**Dual-boot soak period:** Both Windows and bazzite-dx remain bootable via rEFInd menu for 30 days. After `aipc doctor` has been green for ≥30 days and the user confirms Windows rollback is not needed, the Windows partition and 30 GB install partition are removed with:
- Future `aipc disk wipe-windows` CLI (interactive confirmation, `aipc doctor` precondition, auto-extends BTRFS)
- Manual fallback: `gparted` + `btrfs filesystem resize` (documented in runbook)

**Boot flow summary:**
1. From Windows: download rEFInd 0.14.0+, verify SHA-256, run `refind-install.bat` as administrator
2. Shrink Windows C: by 150 GB → create 30 GB exFAT AIPC_LIVE partition → extract vmlinuz + initrd to ESP, LiveOS to AIPC_LIVE
3. Reboot → rEFInd menu → select "bazzite-installer" → installer boots from local ISO
4. Bazzite installer: target 120 GB unallocated (NOT "use entire disk") → bazzite-dx installs
5. Post-install: rEFInd menu shows bazzite-dx + Windows Boot Manager → verify both boot
6. After 30-day soak: wipe Windows + 30 GB partition → extend BTRFS

**Risks and mitigations:**
| Risk | Mitigation |
|---|---|
| Bricked bootloader → no install media | WinRE on disk + mandatory pre-flight System Image Backup (D5) |
| rEFInd not registering on this firmware | `bcdedit` chainload fallback documented in runbook (Q1) |
| Bazzite installer wipes Windows by accident | "Install to unallocated space only" (D4), explicit user disk selection step, no automation |
| 30-day dual-boot soak forgotten → disk waste | `aipc doctor` adds "stale Windows partition detected, day N of soak" note (future work) |

**Convergence:** Both paths (R6a USB Live and R6b Windows-direct) converge on the same vanilla bazzite-dx host state before `install-aipc-linux.sh` runs (which delegates to the bootstrap phases). From that point onward, §9.5 Bootstrap and §9.6 First-boot Wizard are identical.

### 9.5 Bootstrap to the aipc Image

```
[ ] Open a terminal (Konsole, default in bazzite-dx)
[ ] Verify network (Ethernet or Wi-Fi)
[ ] Run:
       ./install-aipc-linux.sh          # guided menu (recommended)
       # or: curl -fsSL https://raw.githubusercontent.com/a9650615/aipc-strix-halo/main/tools/bootstrap.sh | bash
    The guided menu shows the install journey, preconditions, and recovery info.
    Direct/curl mode runs bootstrap phases without the menu:
       a. Probes hardware (XDNA presence, gfx1151, RAM size)
       b. Asks: "switch to :stable (recommended) or :rolling?"
       c. Imports the user's age public key (from prompt or USB)
       d. `bootc switch ghcr.io/<user>/aipc:<tag>`
       e. Triggers reboot
[ ] Machine reboots into the aipc image
```

### 9.6 First-boot Wizard (`aipc init`)

```
[ ] On first login after bootc switch, `aipc init` auto-runs (systemd user unit)
    Wizard steps:
       a. Hardware report (rocm-smi / xdna-smi snapshot)
       b. Ask name + voice profile (CosyVoice voice clone optional)
       c. Ask primary language (zh-TW default for this user)
       d. Ask which agents to enable (file / browser / screen / calendar / search)
       e. Ask for API keys (Anthropic, OpenAI, search providers) — optional, encrypted via SOPS
       f. Ask Steam credentials — optional
       g. Pull model weights to /var/lib/aipc-models (~50-100 GB, takes time)
       h. Start service tree (LiteLLM → Lemonade → Ollama → Pipecat → …)
[ ] `aipc doctor` runs final verification
[ ] Voice assistant active; say wake word to begin
```

### 9.7 Rollback Insurance

At every step, the **previous deployment** stays bootable from GRUB. If anything goes wrong post-bootc-switch:

```
1. Reboot, hold Spacebar at firmware → GRUB
2. Choose "ostree previous deployment"
3. Boot back to vanilla bazzite-dx
4. Investigate, fix, retry bootc switch
```

If both deployments are unbootable, the bazzite USB stick re-installs from scratch in 10 minutes. User data on `/var/home` and `/var/lib/aipc-models` survives a reinstall when the BTRFS layout is preserved (advanced; covered in `docs/recovery.md`).

### 9.8 Time Estimate

| Step | Time |
|---|---|
| §9.1 Windows pre-flight | 30 min |
| §9.2 BIOS prep | 10 min |
| §9.3 USB creation | 15 min |
| §9.4 Bazzite install | 15 min |
| §9.5 Bootstrap + bootc switch | 20 min (image pull) |
| §9.6 First-boot wizard + model pull | 30-90 min (depends on bandwidth) |
| **Total first-time install** | **~2.5 hours** |

Subsequent rebuilds (same machine, different machine, friend's machine) skip §9.1 and complete in ~1 hour.

---

## 10. Phase 0 Hardware Verification Checklist

Phase 0 is intentionally manual-first: verify the hardware on the actual AMD Ryzen AI MAX+ 395 machine **before committing any of the stack to a Containerfile**. The project owner runs this once on the first install, on top of vanilla bazzite-dx (after §9.1-§9.4). Everything below the line then becomes a tracked module.

```
[ ] BIOS: UMA framebuffer set to minimum (512 MB or 1 GB)
[ ] BIOS: Smart Access Memory enabled
[ ] Kernel ≥ 6.14 booted
[ ] dmesg | grep amdgpu reports GTT ≈ 120 GB
[ ] rocm-smi recognises gfx1151
[ ] xdna-smi (or amd-smi) recognises XDNA 2
[ ] llama.cpp loads Qwen2.5-72B-Q4 without OOM
[ ] Lemonade SDK can load a small ONNX model on NPU
[ ] Concurrent: 70B LLM + SenseVoice + 8 GB free for desktop
[ ] CosyVoice 2 Chinese output passes the user's listening test
[ ] SenseVoice Chinese transcription baseline measured
[ ] Pipecat end-to-end demo (text input, text output) runs
```

Each failed item becomes an OpenSpec change before Phase 1 proceeds.

---

## 11. Repository Layout

```
aipc_setup/
├── openspec/
│   ├── project.md                 # this file
│   ├── AGENTS.md                  # rules for AI working in this repo
│   ├── specs/<capability>/        # per-capability specs (populated by archived changes)
│   └── changes/<id>-<slug>/       # active change proposals
├── modules/                       # 46 modules (see §7)
├── targets/
│   ├── bootc/Containerfile        # primary render
│   └── ansible/                   # fallback render
├── tools/
│   ├── aipc                       # CLI (init / doctor / models / image)
│   └── bootstrap.sh               # thin wrapper → install-aipc-linux.sh --direct
├── Install-AIPC-Windows.ps1       # guided Windows entry point (menu + USB SSD + no-USB)
├── install-aipc-linux.sh          # guided Linux entry point (menu + bootstrap phases)
├── secrets/                       # SOPS-encrypted YAML (no plaintext)
├── .github/workflows/             # CI: build + push :rolling, :stable, :YYYY-MM-DD
├── docs/                          # human-facing docs (architecture diagrams, ADRs)
└── README.md
```

---

## 12. Constraints, Risks, and Open Questions

| Area | Constraint / Risk | Mitigation |
|---|---|---|
| Strix Halo is bleeding-edge silicon (2025) | ROCm / XDNA support evolves week by week | Phase 0 manual verify; pin module versions; revisit pins monthly |
| Lemonade SDK Linux story newer than Windows | Possible undocumented edge cases | Validate in Phase 0; fall back to "iGPU only" if blocked |
| Pipecat + Lemonade integration not an AMD demo | Custom processor required | Ship our own Pipecat processor; ~50 LoC Python wrapper |
| CosyVoice 2 Chinese quality vs Kokoro-zh | TBD by user listening test | Dual-install; user picks default at first-boot wizard |
| Screen-control agent capability | Privacy / safety sensitive | Explicit session gate (`agent screen on`); window blacklist (password managers, banking); audit log |
| Image size with ROCm | Layer ~30 GB | Bake ROCm; keep model weights out via BTRFS bind mount; downloads are layer-diffs |
| GitHub Actions free tier | 2000 min/month private | Keep `aipc` repo public; tracks zero cost at planned cadence |
| AGPL / license drift across 40+ upstream tools | License obligations vary | Track in `docs/licenses.md`; user repo stays MIT |
| User new to bootc / Universal Blue | Learning curve | Phase 0 documentation; emergency rollback `bootc switch ghcr.io/ublue-os/bazzite-dx:latest` always works |
| Wiping Windows is destructive and irreversible | User loses pre-installed Windows; no in-place dual boot in v1 | §9.1 pre-flight checklist; BitLocker recovery key backed up; OEM key recorded; bazzite USB always re-installs |
| Strix Halo Wi-Fi 7 firmware in older kernels | Possible no network at bazzite first boot if installer image lags | §9.4 fallback: USB-Ethernet adapter recommended for install day; kernel ≥ 6.14 in current bazzite-dx ships the firmware |
| Secure Boot disabled in v1 | Reduced boot integrity guarantees | Documented choice; OpenSpec change to enrol MOK and re-enable Secure Boot planned for v2 |
| BIOS EXPO / SAM not enabled by default on some shipping units | Reduced memory bandwidth, missed unified-memory perf | §9.2 BIOS checklist; `aipc doctor` reports DDR speed and SAM state |
| Idle memory drift (specialist models holding GTT after use) | Erodes the "Mac-like fluidity" the unified-memory design promises | Owned by `modules/llm-lemonade/` (primary local backend as of 2026-07-05): `resident-small` stays resident via NPU/FLM, `coder-agentic`/`ornith-35b` stay resident via `max_loaded_models=2` (Lemonade has no per-model keep_alive knob, unlike Ollama). `llm-ollama`'s `OLLAMA_KEEP_ALIVE` knob still exists but is unused while idle. vLLM eviction remains an open gap (see `llm-litellm` README). Reviewed in Phase 1. Power-management deferred to Phase 7 (no `ops-power` module in v1). |

---

## 13. Definition of Done (per phase)

A phase is complete when:

1. Every module in the phase has `verify.sh` passing on the user's hardware.
2. `aipc doctor` reports OK for the phase.
3. An OpenSpec change has been archived (specs updated) for any deviation from this document.
4. The image at `ghcr.io/<user>/aipc:rolling` builds cleanly in CI.
5. A `:YYYY-MM-DD` immutable tag exists so the phase can be reverted to.

Phase 7 (Ops) is "complete" continuously — backups, doctor, and first-boot must keep passing forever; their CI runs are gating for all later changes.
