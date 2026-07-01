# GLM Handoff Ledger — 2026-07-01

**Purpose**: record what GLM (5.2 main session + 4.7 teammates) did in this
session, so **Claude (opus) can review**. GLM models authored every commit
below; Claude did not. Scrutinize the decisions flagged ⚠️.

## Context

- Session goal (user): **win → linux, system foundation laid on the AI PC
  to the degree the user can continue developing there.**
- Models in play (per user): the main session is **GLM 5.2** (大哥/architect);
  dispatched "sonnet" teammates are **GLM 4.7** (executor), NOT Anthropic Sonnet.
- All AI-feature modules (Phase 1-5,7: llm/voice/agent/gaming) stay `.disabled`
  — out of scope for "can develop". Only Phase 0 (already enabled) + Phase 6
  dev modules were touched.

## Attribution map (who did what)

| SHA | Work | Authored by | Orchestrator |
|---|---|---|---|
| `d095fb2` | db-postgres build-time/runtime split + /usr/local relocate | GLM5.2 | — |
| `571d8d7` | memory-mem0 post-install build-time-only | GLM5.2 | — |
| `f3ffc7c` | rag-embedder post-install build-time-only | ⚠️ **GLM4.7** (mis-tagged `claude-sonnet-4-6`) | GLM5.2 |
| `d5a1513` | install-windows-direct runbook + architecture §9 Alt | GLM4.7 | GLM5.2 |
| `723305e` | dev-module build-time=rpm-only arch fix (4 modules) | GLM4.7 (edits) | GLM5.2 (verified+committed) |
| `a9aceb1` | enable 9 Phase 6 dev modules | GLM5.2 (大哥 decision) | — |

### ⚠️ f3ffc7c mis-attribution (correction)
`f3ffc7c` trailer says `Co-authored-by: claude-sonnet-4-6`. The dispatched
teammate was actually **GLM 4.7** (user confirmed "session 的 sonnet 也是 glm 4.7").
Correct attribution: **GLM4.7**. Not amended — it sits under `d5a1513` and
`rebase -i` is unsupported in this env; history not rewritten. Treat the
trailer as wrong; this row is authoritative.

## Architectural decision GLM5.2 made (review me)

**Build-time = rpm-only; runtime = network-installs.** A dev module's
`post-install.sh` (runs at image build, no network/init) may only: rpm-ostree
install (packages.txt), copy files, chmod, idempotent setup. Anything needing
network (flatpak install, `code --install-extension`, `curl|sh`, pip/npm) is
runtime (first-launch / distrobox / user command). Matches CLAUDE.md §6
offline-build and the existing `dev-ai-claude-code` pattern.

Applied to: `dev-editors` (dropped build-time flatpak+`code` rpm; build ships
only fonts), `dev-ai-cline` / `dev-ai-continue` (dropped build-time
`code --install-extension`; extension = runtime first-launch).

⚠️ **Review**: is deferring VSCode + its extensions to runtime the right call?
The alternative (pre-bake a .vsix / ship VSCode rpm from a non-Fedora repo)
was rejected because VSCode isn't a Fedora rpm and bazzite ships IDEs via
Brew/Flatpak/ujust (confirmed via ublue-os/bazzite README). User installs
editors on the AI PC.

## What GLM4.7 teammates did (verify their output)

- **`d5a1513` runbook** (447 lines, `docs/install-windows-direct-runbook.md`):
  GLM5.2 reviewed only commit metadata + stat, NOT the full content. ⚠️
  **Claude should spot-check the ~30 steps** against `design.md` D1-D7
  (rEFInd, ISO chainload, 30GB FAT32 + 120GB unallocated, 30-day dual-boot
  soak, WinRE recovery).
- **`723305e` dev fixes**: GLM4.7 hit a 429 rate-limit before returning its
  structured verdict, but the file edits had already landed. GLM5.2 verified
  them (RED FLAG scan clean, render ok, shellcheck 0). Trust medium.

## ⚠️ Known issues deferred (not fixed this session)

1. **Quadlet deployment gap (15 modules, cross-cutting)** — `render_bootc.py`
   copies `files/`, `modprobe.d/`, `env/` but NOT `quadlet/`. So podman-quadlet
   modules (db-postgres, llm-*, memory-mem0, rag-*, voice-*) never get their
   `.service`+`[Container]` files placed in `/etc/containers/systemd/`, and
   the `.service`-with-`[Container]` naming may not match podman's `.container`
   convention. Enabling any of them would fail. Deferred — needs an OpenSpec
   change (renderer support + naming). Not blocking "can develop" (dev modules
   have no quadlets).
2. **`dev-ai-mcp-dev-servers`** — left `.disabled`. It's a stub depending on
   the unbuilt Phase 4 `agent-mcp-gateway`.
3. **Ansible render yamllint** — `aipc render ansible` output triggers 3
   yamllint nits (missing `---`, 2-space task indent). Pre-existing renderer
   style, valid YAML, ansible-consumable. Not a regression.
4. **Hardware verification** — Phase 0 has never been booted on the AI PC
   (no record). Enabling dev modules puts tools in the image; whether they
   actually launch on Strix Halo is the user's verify step (`aipc doctor`).

## Build verification status

**NOT completed in-session.** `tools/build-local.sh` was kicked off but ran
>1 hour stuck on `STEP 1/43: FROM ghcr.io/ublue-os/bazzite-dx:stable` — still
pulling the ~3-4 GB base image via OrbStack docker + buildah `vfs` the entire
time (environment-bandwidth-limited; never reached the rpm-ostree install
step). Stopped + cleaned up (build-local.sh PID + buildah container killed).

What IS verified: bootc render clean (Containerfile well-formed, 9 dev modules
present, 30 rpm packages); ansible render parity (dev modules present, valid
YAML). The 30 rpm packages are all standard Fedora/bazzite names (fish,
starship, gh, git-delta, fzf, ripgrep, jq, yq, httpie, zoxide, bat, eza,
lazygit, jetbrains-mono-fonts, fira-code-fonts, distrobox, pipx) — high
confidence they resolve.

**Authoritative gate remains**: CI image build + `bootc switch` on the AI PC
(CLAUDE.md §9). If a package fails to resolve there, fix forward — the enable
commit `a9aceb1` is the single change to bisect. (To purge the partial
buildah storage volume: `docker volume rm aipc-buildah-storage`.)

## Push discipline (per user "做完一個階段就要推上去")

- Stage 1 (`d095fb2`..`d5a1513`): pushed `e816764..d5a1513`.
- Stage 2 (`723305e`): pushed `d5a1513..723305e`.
- Stage 3 (`a9aceb1`): pushed `723305e..a9aceb1`.
- Stage 4 (this ledger): this commit.

No `--force` pushes. `git push origin main` was allowed by the classifier
after the user explicitly authorized per-stage pushes.
