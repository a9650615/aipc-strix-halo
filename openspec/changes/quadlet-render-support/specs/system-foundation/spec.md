## MODIFIED Requirements

### Requirement: Dual Rendering From Modules

The repo SHALL render the same `modules/` source into both a bootc Containerfile and an Ansible playbook such that both renderings produce identical `aipc doctor` output on a fresh Fedora-based host.

Both renderers SHALL consume the same set of module subdirectories and place each at the same destination:

| Subdirectory | Destination |
|---|---|
| `files/` | `/` |
| `modprobe.d/` | `/etc/modprobe.d/` |
| `env/` | `/etc/aipc/env.d/<module>/` |
| `quadlet/` | `/etc/containers/systemd/` |

A module's `quadlet/` directory SHALL contain only podman-quadlet source files (`*.container`, `*.pod`, `*.volume`, `*.network`). Plain systemd units (no `[Container]` section) SHALL be shipped via `files/etc/systemd/system/` instead. Modules SHALL NOT hand-install their own units inside `post-install.sh`; placement is the renderer's responsibility.

#### Scenario: `aipc render bootc` succeeds

- **WHEN** the project owner runs `aipc render bootc --image-ref ghcr.io/example/aipc:test --build-date 2026-06-27`
- **THEN** the command exits 0 and writes a non-empty file to `targets/bootc/Containerfile.generated` that contains a `FROM` directive and at least one `rpm-ostree install` line

#### Scenario: `aipc render ansible` succeeds and lints

- **WHEN** the project owner runs `aipc render ansible` followed by `ansible-lint targets/ansible/site.generated.yml`
- **THEN** both commands exit 0

#### Scenario: Both renderers place quadlet units

- **WHEN** a module ships a `quadlet/foo.container` file and is enabled
- **THEN** the bootc render COPYs it to `/etc/containers/systemd/` AND the ansible render copies it to `/etc/containers/systemd/`, so podman-quadlet generates `foo.service` at boot on either target

#### Scenario: Renderers agree on consumed subdirectories

- **WHEN** a module ships `files/`, `modprobe.d/`, `env/`, and `quadlet/`
- **THEN** both `render_bootc` and `render_ansible` reference all four subdirectories at the destinations in the table above; a renderer that omits any subdirectory fails the render-parity test

#### Scenario: Renderings agree on doctor output

- **WHEN** an OpenSpec-validated Phase 0 image (built via the bootc render) and a clean Fedora VM provisioned via the Ansible render both run `aipc doctor` on identical hardware
- **THEN** the two `aipc doctor` outputs report the same module count and the same per-module OK/FAIL status
