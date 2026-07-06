# agent-code-shell

Distrobox sandbox for agent code execution (D3, phase-4-agent tasks
1.2, 3.1, 3.2, 3.3). Ships `.disabled` — render-verified only, no
hardware-verified claim exists yet (CLAUDE.md §9).

## Current status: safety wrapper implemented, distrobox itself untested here

Implemented this session:

- **Template** (task 3.1): `files/etc/aipc/distrobox/templates/agent-runtime.yaml`
  — distrobox-assemble manifest (INI syntax despite the `.yaml` extension;
  distrobox-assemble only understands INI, same reasoning as
  `dev-distrobox-templates/README.md`'s `.ini` files — the path/name here is
  fixed by `openspec/changes/phase-4-agent/specs/agent-runtime/spec.md`, not
  chosen by this module). Fedora 41 toolbox base, Python 3.12 (Fedora 41's
  default `python3`), one explicit workspace mount
  (`~/aipc-workspace:/workspace:rw`), `home=` overridden to an isolated
  directory, and `init_hooks` installing Open Interpreter (task 3.3) the
  first time the box is assembled.
- **Wrapper** (tasks 1.2/3.2): `files/usr/lib/aipc-agent/aipc-code-shell`,
  symlinked onto `PATH` at `/usr/bin/aipc-code-shell` by `post-install.sh`.
  Every invocation runs `distrobox enter agent-runtime -- <cmd>` — this is
  the module's only exec path; there is no direct-subprocess fallback.
  Refuses (non-zero exit, no subprocess call at all) in two cases instead of
  silently falling back to an unsandboxed run:
  1. `distrobox` isn't on the host `PATH`.
  2. the wrapper is invoked from a process that's already inside a
     container (detected via `/run/.containerenv`, the standard podman/OCI
     marker file also present inside distrobox boxes). Re-entering
     `distrobox enter` from inside a sandbox doesn't add sandboxing, it just
     obscures which namespace the command actually lands in — see
     `dev-distrobox-templates/README.md`'s documented `sudo`/
     `distrobox-host-exec` bridge for a concrete example of that class of
     footgun in this exact toolchain.
- **verify.sh**: checks the wrapper exists and is executable, then actually
  runs `aipc-code-shell --self-test`, which drives the refusal logic
  directly (fake container marker → refused, zero subprocess calls; no
  marker → the subprocess argv is asserted to be exactly
  `["distrobox", "enter", "agent-runtime", "--", ...]`) — a real behavioral
  check, not just file presence.

## Known gap: distrobox's default host-`$HOME` bind mount is NOT suppressed

Verified directly against the distrobox binary actually installed on this
dev machine (`distrobox 1.8.2.5`) — `distrobox assemble create --dry-run`
against this module's template, and reading `distrobox-create`'s own source
(the unconditional "Mount user home, dev and host's root inside container"
block, plus the separate always-on `/var/home/<user>` mount for ostree
hosts): **`home=` only changes the container's effective `$HOME` env var
and where distrobox points its own custom-home mount. It does NOT stop
distrobox from also bind-mounting the real host home directory
(`/home/<user>` and, on ostree hosts like this repo's target, also
`/var/home/<user>`) at its original path.** There is no `--no-home` /
`--unshare-home` flag in this distrobox version — `--unshare-all` does not
touch this mount either (confirmed by dry-run), and would additionally drop
`--network host`, which breaks the CLAUDE.md §7 requirement that Open
Interpreter reach the LiteLLM gateway at `127.0.0.1:4000` on the host — so
it's not used here.

Net effect: the spec's "no $HOME mount" is achieved for the container's
*effective* home (`$HOME`, and therefore anything using it, like `pip
install --user`) — but the real host home directory is still reachable
inside the container at its original absolute path, because distrobox
itself always mounts it. Closing this gap fully would mean not using
`distrobox assemble`/`distrobox create` for this container at all (a direct
`podman create` invocation with a hand-built mount list), which is a bigger
scope change than this dispatch — flagging it here rather than silently
shipping a template that looks like it satisfies the requirement but
doesn't fully.

## Task 3.3 (Open Interpreter): declarative, not a post-install.sh step

`post-install.sh` runs at image build time with no distrobox/podman daemon
alive (CLAUDE.md §8's build-time/runtime split) — it cannot itself run
`distrobox assemble create` or install anything inside a container that
doesn't exist yet. The template's own `init_hooks="pip3 install --user
open-interpreter"` is distrobox's built-in mechanism for exactly this: it
runs once, on the machine, the first time the user (or a runtime unit) does
`distrobox assemble create --file /etc/aipc/distrobox/templates/agent-runtime.yaml`.
`post-install.sh` only ships the template file and installs the wrapper —
nothing here spawns the box.

## Verification

- **Static**: `sh -n` on `post-install.sh`/`verify.sh`; `python3 -m
  py_compile` on the wrapper. All pass.
- **Self-test** (see verify.sh above): `aipc-code-shell --self-test` passes
  — refusal-when-already-in-container, refusal-when-no-cmd, and
  success-path-argv-is-always-distrobox-enter, all asserted directly.
- **Render-verified**: `tools/aipc render bootc` and `tools/aipc render
  ansible --check` both include this module's new template/wrapper/symlink
  steps; full `pytest` suite (135 tests before this change) stays green.
- **Not hardware-verified**: this session has no access to the physical
  Strix Halo AI PC. `distrobox assemble create --dry-run` was run locally
  against the real distrobox binary to validate INI syntax and the
  `$HOME`-mount finding above, but the container was never actually created
  or entered, Open Interpreter's `init_hooks` install was never executed,
  and `distrobox enter agent-runtime -- interpreter --version` (the spec's
  own verification scenario) was not run. Module stays `.disabled` per
  CLAUDE.md §9 until that happens.

## Dependencies
- dev-distrobox-templates (podman/distrobox runtime already installed by
  `system-base`; this module doesn't reuse `dev-distrobox-templates`'
  node/python templates directly — the agent sandbox has different security
  requirements, see the `$HOME`-mount section above)
- llm-litellm

## Spec
openspec/changes/phase-4-agent — tasks 1.2, 3.1, 3.2, 3.3
