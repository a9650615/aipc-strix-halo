# Disk + layer hygiene (bootc / buildah / podman)

Standing note after the 2026-07-10 disk pressure investigation on the Strix Halo
host. **Essential model weights are not the only (or always the first) culprit.**
Incomplete image-layer work leaves large, hard-to-spot residue.

Machine-wide pitfall also recorded as **claude-ops `LESSONS.md` L5**.

## Policy (user)

**Layers may be rebuilt and iterated.** Prefer small safe steps over one big
cleanup. **Do not brick the running host** — keep a rollback until a new layer is
hardware-verified (voice / lemonade / litellm at minimum).

## What "dirty layer" means here

| Store | Where | Typical dirt |
|---|---|---|
| **User podman** | `~/.local/share/containers` | Local `podman build` / `buildah` of aipc or bazzite; intermediate layers; abandoned working containers |
| **Root podman** | `/var/lib/containers` | Runtime images (lemonade, litellm, postgres) — usually small if not hoarding tags |
| **ostree / bootc** | `/ostree/deploy`, `/ostree/repo` | Multiple deployments (booted + staged/pending + rollback); live unlock / InterruptedLiveCommit; rpm-ostree private extensions |

Hardlinks make `podman images` **Size columns overstate** disk use; trust
`podman system df` **RECLAIMABLE** and `df -h /var`.

## Dirty patterns (do not repeat)

### D1. Interrupted buildah / bootc local builds

**Symptom:** huge reclaimable; dozens of `<none>` ~18–19G entries; `podman ps -a`
almost empty.

**Real residue:** external containers status **`Storage`**, names
`*-working-container` (buildah left when multi-stage / bootc build is killed).

```bash
podman container ls -a --external
```

**Clean (safe shape):**

```bash
podman container ls -a --external --format '{{.ID}} {{.Names}} {{.Status}}' \
  | awk '/working-container/ {print $1}' \
  | xargs -r podman rm -f --storage
podman image prune -a -f
```

**Anti-pattern:** `buildah rm --all` without checking — can untag images still used
by long-lived containers (toolbox, TTS).

### D2. Full OS images in *user* podman after experiments

Usually unnecessary on a bootc host:

- `ghcr.io/a9650615/aipc:rolling`
- `localhost/aipc:local-test`
- `ghcr.io/ublue-os/bazzite-dx:stable` (build base only)

After experiments: drop tags, then `podman image prune -a -f`.

### D3. ostree deployments never pruned

```bash
rpm-ostree status
sudo ostree admin status
sudo du -xsh /ostree/deploy /ostree/repo \
  /ostree/repo/extensions/rpmostree/private
```

Red flags: `Unlocked: transient`, `InterruptedLiveCommit`, forever staged/pending,
forever rollback, large `rpmostree/private`.

### D4. Live hotfix without closing the loop

See `docs/live-hotfix-workflow.md`. Hotfix is fine; not finishing unlock / not
pruning deploys / not removing buildah working-containers is what fills the disk.

### D5. Blaming only models

Do not delete model trees before the diagnose block below. Essential (when hunting
*dirt*, leave alone): `/var/lib/aipc-models/hf`, `/var/lib/aipc-voice`,
`/var/lib/aipc-lemonade`.

## Diagnose block

```bash
df -h /var
podman system df
podman container ls -a --external | head -40
sudo podman system df
rpm-ostree status | head -40
sudo du -xsh /ostree/deploy /ostree/repo \
  /ostree/repo/extensions/rpmostree/private 2>/dev/null
sudo du -xsh /var/lib/aipc-models/hf /var/lib/aipc-voice /var/lib/aipc-lemonade 2>/dev/null
```

## Careful re-layer plan (iterate; do not one-shot)

| Step | Action | Risk | Status |
|---|---|---|---|
| **0** | User podman: buildah `*-working-container` + unused aipc/bazzite tags | Low if only Storage leftovers | **Done** 2026-07-10 (~26–31G free) |
| **1** | `sudo rpm-ostree cleanup -p` — drop **staged/pending only** | Low: running system unchanged; can re-stage later | **Done** 2026-07-10: removed `72f13aa…`; `/ostree/deploy` **72G→56G** |
| **2** | Clear **Unlocked: transient** / `InterruptedLiveCommit` | Medium: needs **planned reboot** (or proper unlock finish). Schedule; do not mid-session | **Pending** |
| **3** | Optional `sudo rpm-ostree cleanup -r` | Medium: loses rollback | **Pending explicit OK** after Step 2 + known-good boot |
| **4** | Clean re-layer: `bootc switch` to known-good registry image | Medium: full switch path; keep rollback until verified | **Later** — avoid stacking more `rpm-ostree install` dirt |

### Safety rules

1. Never batch `-p` + `-r` + reboot untested.
2. Keep **one** known-good rollback until voice/lemonade/litellm verified on the new layer.
3. Prefer module/repo durable fixes over `rpm-ostree install` temporary packages (`Diff: N added` becomes permanent dirt).
4. After any local buildah/bootc build: prune working-containers (D1) before calling the host clean.

### After Step 2 (reboot checklist)

```bash
rpm-ostree status          # expect no Unlocked / InterruptedLiveCommit
systemctl is-active lemonade litellm
curl -sS -m 3 http://127.0.0.1:4000/v1/models | head -c 80
curl -sS -m 3 http://127.0.0.1:8880/health
aipc voice status 2>/dev/null || true
df -h /var
```

Only then consider Step 3 (`cleanup -r`) or Step 4 (fresh `bootc switch`).

## Snapshot 2026-07-10 (this host)

| Item | Value |
|---|---|
| Booted | `4fd3bcc…1` digest `fae4f39e…`, still **Unlocked: transient** after Step1 |
| Rollback | `4fd3bcc…0` same digest family — **kept** |
| Staged removed | `72f13aa…` digest `3411c186…` via `cleanup -p` |
| Package dirt on booted | origin requests `libglvnd-glx` (layer add) — clean switch later can drop |
| `/var` after podman+Step1 | ~382–383G used / ~115G free (was ~408G / 91G before layer cleanup) |
EOF