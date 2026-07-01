# Design — quadlet-render-support

## D1 — Quadlet destination: `/etc/containers/systemd/` (system, root)

podman-quadlet's generator (`podman-system-generator`) scans, in order:
`/etc/containers/systemd/`, `/usr/share/containers/systemd/`, and — for the
user generator — `~/.config/containers/systemd/`. Modules ship `*.container`
source files; the generator turns each into a runtime `*.service` unit at boot.

**Chosen:** COPY `modules/<m>/quadlet/` → `/etc/containers/systemd/` (system-level,
root-run containers).

- Alternatives: `/usr/share/containers/systemd/` (vendor path — reserved for
  base-image content, not overlay config), user path `~/.config/...` (per-user,
  no root, requires a logged-in session + lingering — wrong for always-on
  inference services).
- Why: these are system services (Ollama, LiteLLM, Postgres, embedder) that must
  start at boot without a user session. `/etc/containers/systemd/` is the config
  path (as opposed to the vendor `/usr/share` path) and is writable in the image
  build.

## D2 — Drop the `--user` quadlet workaround in llm-litellm

`llm-litellm/post-install.sh` currently copies its unit to
`~/.config/containers/systemd/litellm.service` and runs `systemctl --user
enable --now`. This is the only user-scoped service and it contradicts D1.

**Chosen:** llm-litellm ships `quadlet/litellm.container` like every other
service module; the renderer places it in `/etc/containers/systemd/`.
post-install.sh drops the `~/.config` copy and the `--user` enable.

- Why: consistency (one placement path), and LiteLLM is the gateway every other
  service depends on — it must be up at boot, not gated on a user login.

## D3 — Drop the hand-install in llm-lemonade

`llm-lemonade/post-install.sh` does `install -D quadlet/lemonade.service
/etc/systemd/system/lemonade.service`. That path is plain-systemd, not quadlet —
lemonade's unit is a `Type=simple` service (not a `[Container]`), so it is
legitimately a systemd unit, not a quadlet. But it should still be shipped as
data via `files/`, not installed imperatively in post-install.

**Chosen:** move `llm-lemonade/quadlet/lemonade.service` (a real systemd unit,
no `[Container]`) to `llm-lemonade/files/etc/systemd/system/lemonade.service`;
post-install stops hand-installing it. The renderer already COPYs `files/`.

- Note: this is the one genuine `.service` in a `quadlet/` dir. After this
  change, `quadlet/` contains only `*.container` (podman) files; anything that
  is a plain systemd unit lives under `files/etc/systemd/system/`. That keeps
  the rule simple: **`quadlet/` = podman container/pod/volume units only.**
- `rag-ingest` has five `aipc-rag-*.service` files in `quadlet/` that are also
  plain systemd units (no `[Container]`). Same treatment: relocate to
  `files/etc/systemd/system/`. After this, `quadlet/` is 100% `*.container`.

## D4 — Renderer parity is enforced by a test, not by discipline

The two renderers drifted precisely because nothing checked they consume the
same module subdirectories. Add a test that asserts: for a synthetic module with
`files/`, `modprobe.d/`, `env/`, and `quadlet/`, both `render_bootc` and
`render_ansible` reference all four. The test fails if either renderer forgets a
subdirectory.

- ponytail: one parity test over the four subdir types, not a per-subdir suite.
  Upgrade path = add a case if a fifth subdir type is ever introduced.

## D5 — Ansible destinations mirror bootc exactly

| Subdir | bootc dest | ansible dest |
|---|---|---|
| `files/` | `/` | `/` (already) |
| `modprobe.d/` | `/etc/modprobe.d/` | `/etc/modprobe.d/` (NEW) |
| `env/` | `/etc/aipc/env.d/<m>/` | `/etc/aipc/env.d/<m>/` (NEW) |
| `quadlet/` | `/etc/containers/systemd/` | `/etc/containers/systemd/` (NEW) |

Ansible `copy` with `src: modules/<m>/<subdir>/` `dest: <dest>` mirrors the
bootc `COPY`. Keep the existing per-module task granularity.

## Open Questions

- **Q1** — Digest pinning of container images in the `*.container` files is out
  of scope here (tracked per-module in phase-1/2 tasks). This change only fixes
  placement, not image references.
- **Q2** — Whether `agent-tools-search/searxng.container` needs a companion
  `.volume` quadlet for its data dir is a phase-4 concern; not decided here.
- **Q3** — Ansible `become: true` runs tasks as root, so `/etc/containers/systemd/`
  is writable there too. Confirmed no user-scoped quadlet remains after D2.
