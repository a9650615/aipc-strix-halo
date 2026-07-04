# dev-distrobox-templates

Distrobox templates for Node and Python development environments.

## What it does

- Installs distrobox.
- Ships INI-format template files at `/etc/aipc/distrobox/{node,python}.ini`
  for use with `distrobox assemble create`. (`.ini` extension so yamllint
  doesn't try to parse them — distrobox-assemble uses INI syntax, not YAML.)

## Templates

- **node**: fedora-toolbox:41 with nodejs, npm, git.
- **python**: fedora-toolbox:41 with python3, pip, devel, git.

## `node`: `sudo` is shadowed to reach the host, not the container

Hardware-verified 2026-07-04: Node-based agent tools (opencode, claude-code,
mcp-dev-servers) run entirely inside this distrobox container, so their
shell tools' `sudo` calls only ever hit the container's own namespace by
default — no `/run/dbus` bridge is mounted in, so even something as basic
as `sudo systemctl status foo` fails with "System has not been booted with
systemd as init system." This is why an agent asked to debug/fix the host
system from inside this container could not, even though the host itself
grants this user passwordless sudo.

`init_hooks` installs a `/usr/local/bin/sudo` wrapper (ahead of the real
`/usr/bin/sudo` on `$PATH`) that forwards every call to
`distrobox-host-exec sudo "$@"` — distrobox's own bridge for running a
command in the host's namespace. This makes `sudo <anything>` typed or
scripted inside the container transparently operate on the real host, with
no opencode/claude-code config changes and no prompt-engineering needed —
it relies on nothing more than the NOPASSWD sudo already granted to this
user at the OS level (see `system-base`), not a new privilege.

Consequence, stated plainly: `sudo dnf install <pkg>` typed inside this
container no longer installs into the container — it runs on the
(ostree/bootc, rpm-ostree-managed) host instead, which is very likely not
what you want. To change what's installed *in the container itself*, edit
`additional_packages` in `node.ini` and recreate the container
(`distrobox rm node && distrobox assemble create --file /etc/aipc/distrobox/node.ini`),
matching this repo's declarative/rebuild-don't-hand-patch philosophy —
don't reach for `sudo dnf` inside the container by hand.

## Dependencies

- `system-base` (podman runtime).

## Consumers

- `dev-ai-aider` (Python template).
- `dev-ai-opencode` (Node template).
- `dev-ai-claude-code` (Node template).
- `dev-ai-mcp-dev-servers` (Node template).
