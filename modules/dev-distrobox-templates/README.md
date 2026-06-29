# dev-distrobox-templates

Distrobox templates for Node and Python development environments.

## What it does

- Installs distrobox.
- Ships INI-format template files at `/etc/aipc/distrobox/{node,python}.yaml`
  for use with `distrobox assemble create`.

## Templates

- **node**: fedora-toolbox:41 with nodejs, npm, git.
- **python**: fedora-toolbox:41 with python3, pip, devel, git.

## Dependencies

- `system-base` (podman runtime).

## Consumers

- `dev-ai-aider` (Python template).
- `dev-ai-opencode` (Node template).
- `dev-ai-claude-code` (Node template).
- `dev-ai-mcp-dev-servers` (Node template).
