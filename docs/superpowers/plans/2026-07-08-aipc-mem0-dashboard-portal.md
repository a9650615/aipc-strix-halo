# AIPC Mem0 Dashboard + Entry Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the local minimal Mem0 surface with the official self-hosted Mem0 dashboard path and add a modular AIPC entry portal that lists installed manageable services.

**Architecture:** `memory-mem0` owns Mem0 and exports portal metadata. New `system-aipc-portal` owns the localhost entry portal and only reads service metadata from `/etc/aipc/portal/services/*.yaml`. `tools/aipc_lib/portal.py` provides CLI helpers for `aipc portal` and `aipc portal open`.

**Tech Stack:** Python stdlib HTTP server for the AIPC portal, PyYAML if already installed or JSON-compatible YAML subset parser if not, systemd units, existing AIPC module renderer, official Mem0 self-hosted server/dashboard after a source/image spike.

## Global Constraints

- Reply/report in Traditional Chinese; code/comments/commit messages in English.
- Keep modules neutral between bootc and ansible render targets.
- Do not bake secrets into the repo.
- Do not hardcode usernames; runtime paths must resolve the primary user dynamically or avoid user paths.
- `post-install.sh` is build-time only: no `systemctl --now`, no live health checks, no network beyond package repos.
- Services bind to `127.0.0.1` only.
- Official Mem0 dashboard is preferred; if it cannot run cleanly, stop and report the blocker instead of writing a custom Mem0 dashboard.
- Portal must not contain Mem0-specific logic; Mem0 appears through metadata.
- Verification claims must name the tier: static, render-verified, or hardware-verified.

---

## File Structure

Create or modify these files:

- Create `openspec/changes/aipc-portal-mem0-dashboard/proposal.md` — scope for official Mem0 dashboard plus AIPC portal.
- Create `openspec/changes/aipc-portal-mem0-dashboard/design.md` — module boundary and local-only dashboard design.
- Create `openspec/changes/aipc-portal-mem0-dashboard/tasks.md` — implementation checklist.
- Create `openspec/changes/aipc-portal-mem0-dashboard/specs/aipc-portal/spec.md` — portal capability requirements.
- Modify `openspec/changes/phase-2-memory/tasks.md` only if needed to point Mem0 dashboard work at the new change.
- Modify `modules/memory-mem0/README.md` — document official dashboard path, local ports, fallback, and verification tier.
- Modify `modules/memory-mem0/env/endpoint` — keep API endpoint or update if official server uses a new API port.
- Create `modules/memory-mem0/env/dashboard` — dashboard URL, expected default `http://127.0.0.1:3000` unless spike selects a different port.
- Create `modules/memory-mem0/files/etc/aipc/portal/services/mem0.yaml` — portal metadata declaration.
- Modify `modules/memory-mem0/files/etc/systemd/system/aipc-mem0.service` — official server unit or wrapper unit selected by spike.
- Create or modify `modules/memory-mem0/files/etc/systemd/system/aipc-mem0-dashboard.service` only if the dashboard must run as a separate process/container.
- Modify `modules/memory-mem0/post-install.sh` — install/build artifacts only; no live service actions.
- Modify `modules/memory-mem0/verify.sh` — check API and dashboard when live, static checks otherwise.
- Create `modules/system-aipc-portal/README.md` — module docs.
- Create `modules/system-aipc-portal/packages.txt` — minimal package list.
- Create `modules/system-aipc-portal/env/endpoint` — `http://127.0.0.1:7080`.
- Create `modules/system-aipc-portal/files/etc/systemd/system/aipc-portal.service` — localhost portal service.
- Create `modules/system-aipc-portal/files/etc/aipc/portal/services/aipc-portal.yaml` — portal self metadata.
- Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/__init__.py` — package marker.
- Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/registry.py` — read metadata and statuses.
- Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/server.py` — HTTP server and HTML rendering.
- Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc-portal` — executable entrypoint.
- Create `modules/system-aipc-portal/post-install.sh` — build-time chmod only.
- Create `modules/system-aipc-portal/verify.sh` — static/live portal checks.
- Create `tools/aipc_lib/portal.py` — CLI status/open helpers.
- Modify `tools/aipc_lib/cli.py` — add `aipc portal` and `aipc portal open`.
- Create `tools/tests/test_portal.py` — parser/render/CLI tests.
- Modify render tests only if module list expectations require it.
- Append one row to `docs/agent-log.md` when implementation is complete.

---

### Task 1: OpenSpec change for portal + Mem0 dashboard

**Files:**
- Create: `openspec/changes/aipc-portal-mem0-dashboard/proposal.md`
- Create: `openspec/changes/aipc-portal-mem0-dashboard/design.md`
- Create: `openspec/changes/aipc-portal-mem0-dashboard/tasks.md`
- Create: `openspec/changes/aipc-portal-mem0-dashboard/specs/aipc-portal/spec.md`

**Interfaces:**
- Consumes: user-approved design in `docs/superpowers/specs/2026-07-08-aipc-mem0-dashboard-portal-design.md`.
- Produces: OpenSpec change `aipc-portal-mem0-dashboard` for implementation tasks.

- [ ] **Step 1: Create proposal**

Write `openspec/changes/aipc-portal-mem0-dashboard/proposal.md`:

```markdown
# AIPC Portal + Mem0 Dashboard

## Why

The AI PC needs a local SaaS-like management surface. Mem0 already has an official self-hosted dashboard, and AIPC needs a separate entry portal that lists installed manageable services without coupling those services together.

## What Changes

- `memory-mem0` runs or integrates the official Mem0 self-hosted dashboard when it is usable on this platform.
- `system-aipc-portal` is added as a first-class AIPC module.
- Manageable modules declare portal cards via `/etc/aipc/portal/services/*.yaml`.
- `aipc portal` and `aipc portal open` expose the entry portal from the CLI.

## Impact

- Adds one module: `system-aipc-portal`.
- Modifies one module: `memory-mem0`.
- Modifies `tools/aipc` CLI.
- Adds local-only web endpoints bound to `127.0.0.1`.
```

- [ ] **Step 2: Create design artifact**

Write `openspec/changes/aipc-portal-mem0-dashboard/design.md`:

```markdown
# Design

## Module boundaries

`memory-mem0` owns Mem0. It exports portal metadata but does not know how the portal renders cards.

`system-aipc-portal` owns the AIPC entry portal. It reads metadata files, checks systemd/health status, and renders cards. It has no Mem0-specific code.

## Network

All web services bind to `127.0.0.1`. No remote management is exposed in this change.

## Metadata contract

Each manageable service installs one YAML file under `/etc/aipc/portal/services/`.

Required keys:

- `id`
- `title`
- `module`
- `kind`

Optional keys:

- `systemd`
- `health`
- `endpoint`
- `ui`
- `tags`

Unknown keys are ignored.

## Mem0 dashboard

Use the official Mem0 self-hosted server/dashboard if it runs on this platform. Prewire it to local Postgres/pgvector, LiteLLM, and `embed-bge`. Runtime secrets are generated on the target machine and never committed.
```

- [ ] **Step 3: Create requirements spec**

Write `openspec/changes/aipc-portal-mem0-dashboard/specs/aipc-portal/spec.md`:

```markdown
# aipc-portal Spec

## ADDED Requirements

### Requirement: AIPC Entry Portal Module

The system SHALL provide a first-class `system-aipc-portal` module that runs a local web entry portal.

#### Scenario: Portal binds locally

- **WHEN** the portal service starts
- **THEN** it listens on `127.0.0.1` only
- **AND** it does not expose a remote management listener.

#### Scenario: Portal discovers services from metadata

- **WHEN** metadata files exist under `/etc/aipc/portal/services/*.yaml`
- **THEN** the portal renders one card per valid metadata file
- **AND** invalid metadata files do not prevent valid cards from rendering.

### Requirement: Portal Metadata Contract

Modules SHALL declare manageable services through metadata files rather than portal-specific code.

#### Scenario: Mem0 appears in portal

- **WHEN** `memory-mem0` installs `mem0.yaml`
- **THEN** the portal shows a Mem0 card
- **AND** the card links to the Mem0 dashboard URL declared by the module.

### Requirement: Portal CLI

The `aipc` CLI SHALL provide `aipc portal` and `aipc portal open`.

#### Scenario: User asks for portal status

- **WHEN** the user runs `aipc portal`
- **THEN** the command prints the portal URL and current availability.

#### Scenario: User opens portal

- **WHEN** the user runs `aipc portal open`
- **THEN** the command opens the portal URL with the system browser command.
```

- [ ] **Step 4: Create task checklist**

Write `openspec/changes/aipc-portal-mem0-dashboard/tasks.md`:

```markdown
# Tasks

- [ ] 1. Spike official Mem0 self-hosted dashboard on this platform.
- [ ] 2. Wire `memory-mem0` to official dashboard or stop with blocker evidence.
- [ ] 3. Add portal metadata for Mem0.
- [ ] 4. Add `system-aipc-portal` module.
- [ ] 5. Add `aipc portal` CLI commands.
- [ ] 6. Run static and render verification.
- [ ] 7. Record verification tier and append `docs/agent-log.md`.
```

- [ ] **Step 5: Validate OpenSpec**

Run:

```bash
openspec validate aipc-portal-mem0-dashboard --strict
```

Expected: validation succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add openspec/changes/aipc-portal-mem0-dashboard docs/superpowers/specs/2026-07-08-aipc-mem0-dashboard-portal-design.md docs/superpowers/plans/2026-07-08-aipc-mem0-dashboard-portal.md
git commit -m "docs: propose aipc portal and mem0 dashboard integration

Co-authored-by: gpt-5.5-high <noreply@anthropic.com>
Agent-Role: 大哥
Agent-Run: aipc-portal-mem0-dashboard-2026-07-08
Spec-Task: aipc-portal-mem0-dashboard#plan"
```

Expected: commit succeeds. If the user does not want commits, skip the commit and report the exact files staged by this task.

---

### Task 2: Official Mem0 self-hosted dashboard spike

**Files:**
- Modify: `modules/memory-mem0/README.md`
- Modify: `openspec/changes/aipc-portal-mem0-dashboard/tasks.md`

**Interfaces:**
- Consumes: official Mem0 docs and source state.
- Produces: a decision in `modules/memory-mem0/README.md`: official dashboard usable or blocker.

- [ ] **Step 1: Inspect official package entrypoints without changing repo code**

Run:

```bash
python3 - <<'PY'
import json, urllib.request
for url in [
    'https://raw.githubusercontent.com/mem0ai/mem0/main/server/docker-compose.yaml',
    'https://raw.githubusercontent.com/mem0ai/mem0/main/server/.env.example',
    'https://raw.githubusercontent.com/mem0ai/mem0/main/server/Makefile',
]:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            text = r.read().decode('utf-8', 'replace')
        print('\n##', url)
        print(text[:4000])
    except Exception as exc:
        print('\n##', url)
        print(type(exc).__name__, exc)
PY
```

Expected: output identifies whether upstream has Docker Compose, required env vars, and dashboard/API ports. If GitHub raw fetch fails because of network policy, use already indexed docs and report that raw source was not fetched.

- [ ] **Step 2: Check image/build feasibility**

Run:

```bash
python3 - <<'PY'
import platform, subprocess
print('machine=' + platform.machine())
for cmd in [['podman', '--version'], ['docker', '--version']]:
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=10).strip()
        print(' '.join(cmd[:1]) + '=' + out)
    except Exception as exc:
        print(' '.join(cmd[:1]) + '=unavailable: ' + type(exc).__name__)
PY
```

Expected: records the local container tool availability. Do not install packages in this step.

- [ ] **Step 3: Update README with spike result**

Add this section to `modules/memory-mem0/README.md` using the actual spike result:

```markdown
## Official dashboard spike

The desired management UI is the official Mem0 self-hosted dashboard, not a custom AIPC dashboard.

Spike result:

- API port: `8888` in upstream docs.
- Dashboard port: `3000` in upstream docs.
- Auth: enabled by default; first admin is created through setup or bootstrap.
- Required secret: `JWT_SECRET`, generated at runtime and not committed.
- Required provider config: wired to local LiteLLM and `embed-bge` where upstream accepts OpenAI-compatible configuration.

Decision: use the official dashboard path if the upstream source/image can be rendered into the module without network-at-runtime or architecture blockers. If that fails, keep the current minimal wrapper and mark the dashboard task blocked with evidence.
```

If the spike finds a blocker, replace the last paragraph with:

```markdown
Decision: blocked. The official dashboard path cannot currently run on this platform because: <single concrete blocker from spike output>. Do not build a custom dashboard as a fallback without a new user-approved change.
```

- [ ] **Step 4: Mark spike task**

In `openspec/changes/aipc-portal-mem0-dashboard/tasks.md`, change task 1 from unchecked to checked only if the spike produced a clear usable-or-blocked decision.

- [ ] **Step 5: Commit**

```bash
git add modules/memory-mem0/README.md openspec/changes/aipc-portal-mem0-dashboard/tasks.md
git commit -m "docs(mem0): record official dashboard spike

Co-authored-by: gpt-5.5-high <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: aipc-portal-mem0-dashboard-2026-07-08
Spec-Task: aipc-portal-mem0-dashboard#1"
```

Expected: commit succeeds, unless the spike is performed by a subagent that uses its own model trailer.

---

### Task 3: Portal metadata contract and Mem0 declaration

**Files:**
- Create: `modules/memory-mem0/env/dashboard`
- Create: `modules/memory-mem0/files/etc/aipc/portal/services/mem0.yaml`
- Modify: `modules/memory-mem0/README.md`
- Modify: `modules/memory-mem0/verify.sh`
- Test: `tools/tests/test_portal.py`

**Interfaces:**
- Consumes: metadata contract from Task 1.
- Produces: `mem0.yaml` metadata parseable by `aipc_portal.registry.load_services(root)` in Task 4.

- [ ] **Step 1: Write failing metadata test**

Create `tools/tests/test_portal.py` with this initial content:

```python
from pathlib import Path

from aipc_lib import portal


def test_load_service_metadata_accepts_mem0_yaml(tmp_path: Path) -> None:
    services = tmp_path / "services"
    services.mkdir()
    (services / "mem0.yaml").write_text(
        """
id: mem0
title: Mem0 Memory
module: memory-mem0
kind: memory
systemd: aipc-mem0.service
health: http://127.0.0.1:8888/health
endpoint: http://127.0.0.1:8888
ui: http://127.0.0.1:3000/
tags:
  - memory
  - dashboard
""".strip()
        + "\n",
        encoding="utf-8",
    )

    loaded = portal.load_service_metadata(services)

    assert len(loaded) == 1
    assert loaded[0].id == "mem0"
    assert loaded[0].title == "Mem0 Memory"
    assert loaded[0].ui == "http://127.0.0.1:3000/"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tools/tests/test_portal.py::test_load_service_metadata_accepts_mem0_yaml -q
```

Expected: FAIL because `aipc_lib.portal` does not exist.

- [ ] **Step 3: Add minimal CLI-side metadata loader**

Create `tools/aipc_lib/portal.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ServiceMetadata:
    id: str
    title: str
    module: str
    kind: str
    systemd: str | None = None
    health: str | None = None
    endpoint: str | None = None
    ui: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


def _parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_metadata(text: str) -> dict[str, object]:
    data: dict[str, object] = {}
    current_list: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_list and stripped.startswith("- "):
            data.setdefault(current_list, []).append(_parse_scalar(stripped[2:]))
            continue
        current_list = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list = key
        else:
            data[key] = _parse_scalar(value)
    return data


def load_service_metadata(root: Path = Path("/etc/aipc/portal/services")) -> list[ServiceMetadata]:
    services: list[ServiceMetadata] = []
    if not root.exists():
        return services
    for path in sorted(root.glob("*.yaml")):
        data = _parse_metadata(path.read_text(encoding="utf-8"))
        try:
            tags = data.get("tags", [])
            services.append(
                ServiceMetadata(
                    id=str(data["id"]),
                    title=str(data["title"]),
                    module=str(data["module"]),
                    kind=str(data["kind"]),
                    systemd=str(data["systemd"]) if data.get("systemd") else None,
                    health=str(data["health"]) if data.get("health") else None,
                    endpoint=str(data["endpoint"]) if data.get("endpoint") else None,
                    ui=str(data["ui"]) if data.get("ui") else None,
                    tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                )
            )
        except KeyError:
            continue
    return services
```

- [ ] **Step 4: Run metadata test**

Run:

```bash
pytest tools/tests/test_portal.py::test_load_service_metadata_accepts_mem0_yaml -q
```

Expected: PASS.

- [ ] **Step 5: Add Mem0 dashboard env file**

Create `modules/memory-mem0/env/dashboard`:

```text
http://127.0.0.1:3000
```

- [ ] **Step 6: Add Mem0 portal metadata**

Create `modules/memory-mem0/files/etc/aipc/portal/services/mem0.yaml`:

```yaml
id: mem0
title: Mem0 Memory
module: memory-mem0
kind: memory
systemd: aipc-mem0.service
health: http://127.0.0.1:8888/health
endpoint: http://127.0.0.1:8888
ui: http://127.0.0.1:3000/
tags:
  - memory
  - dashboard
```

If the official spike selects different ports or paths, use those exact values consistently in `env/endpoint`, `env/dashboard`, metadata, systemd, and verify scripts.

- [ ] **Step 7: Extend Mem0 verify for dashboard metadata**

Modify `modules/memory-mem0/verify.sh` to include static checks before live checks:

```sh
[ -f "$this_dir/env/dashboard" ] || fail "dashboard endpoint missing"
[ -f "$this_dir/files/etc/aipc/portal/services/mem0.yaml" ] || fail "portal metadata missing"
```

Keep the existing behavior where static checks pass if the service is not installed/live on the current host.

- [ ] **Step 8: Run targeted checks**

Run:

```bash
pytest tools/tests/test_portal.py -q
modules/memory-mem0/verify.sh
```

Expected: pytest PASS. `verify.sh` exits 0 with static/render wording if no live installed service exists.

- [ ] **Step 9: Commit**

```bash
git add tools/aipc_lib/portal.py tools/tests/test_portal.py modules/memory-mem0/env/dashboard modules/memory-mem0/files/etc/aipc/portal/services/mem0.yaml modules/memory-mem0/README.md modules/memory-mem0/verify.sh
git commit -m "feat(portal): add mem0 service metadata

Co-authored-by: gpt-5.5-high <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: aipc-portal-mem0-dashboard-2026-07-08
Spec-Task: aipc-portal-mem0-dashboard#3"
```

---

### Task 4: `system-aipc-portal` module

**Files:**
- Create: `modules/system-aipc-portal/README.md`
- Create: `modules/system-aipc-portal/packages.txt`
- Create: `modules/system-aipc-portal/env/endpoint`
- Create: `modules/system-aipc-portal/files/etc/systemd/system/aipc-portal.service`
- Create: `modules/system-aipc-portal/files/etc/aipc/portal/services/aipc-portal.yaml`
- Create: `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/__init__.py`
- Create: `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/registry.py`
- Create: `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/server.py`
- Create: `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc-portal`
- Create: `modules/system-aipc-portal/post-install.sh`
- Create: `modules/system-aipc-portal/verify.sh`
- Test: `tools/tests/test_portal.py`

**Interfaces:**
- Consumes: service metadata files under `/etc/aipc/portal/services`.
- Produces: HTTP `GET /` returning service cards and `GET /healthz` returning `ok`.

- [ ] **Step 1: Add failing HTML render test**

Append to `tools/tests/test_portal.py`:

```python
def test_render_portal_html_links_to_declared_ui() -> None:
    service = portal.ServiceMetadata(
        id="mem0",
        title="Mem0 Memory",
        module="memory-mem0",
        kind="memory",
        ui="http://127.0.0.1:3000/",
        tags=("memory", "dashboard"),
    )

    html = portal.render_portal_html([service])

    assert "Mem0 Memory" in html
    assert "http://127.0.0.1:3000/" in html
    assert "Open" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tools/tests/test_portal.py::test_render_portal_html_links_to_declared_ui -q
```

Expected: FAIL because `render_portal_html` does not exist.

- [ ] **Step 3: Add shared HTML renderer to CLI helper**

Append to `tools/aipc_lib/portal.py`:

```python
import html


def render_portal_html(services: list[ServiceMetadata]) -> str:
    cards = []
    for service in services:
        title = html.escape(service.title)
        module = html.escape(service.module)
        kind = html.escape(service.kind)
        endpoint = html.escape(service.endpoint or "")
        health = html.escape(service.health or "")
        link = ""
        if service.ui:
            href = html.escape(service.ui, quote=True)
            link = f'<a class="button" href="{href}">Open</a>'
        cards.append(
            f"""
            <article class="card">
              <h2>{title}</h2>
              <p class="meta">{module} · {kind}</p>
              <p>Endpoint: <code>{endpoint or 'not declared'}</code></p>
              <p>Health: <code>{health or 'not declared'}</code></p>
              {link}
            </article>
            """
        )
    body = "\n".join(cards) or '<p class="empty">No AIPC services declared yet.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIPC Portal</title>
<style>
body {{ margin: 0; font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 32px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
.card {{ background: #111827; border: 1px solid #334155; border-radius: 14px; padding: 18px; }}
.meta {{ color: #94a3b8; }}
code {{ color: #bae6fd; overflow-wrap: anywhere; }}
.button {{ display: inline-block; margin-top: 8px; padding: 8px 12px; border-radius: 10px; background: #38bdf8; color: #082f49; text-decoration: none; font-weight: 700; }}
.empty {{ color: #94a3b8; }}
</style>
</head>
<body><main><h1>AIPC Portal</h1><section class="grid">{body}</section></main></body>
</html>"""
```

- [ ] **Step 4: Run renderer test**

Run:

```bash
pytest tools/tests/test_portal.py::test_render_portal_html_links_to_declared_ui -q
```

Expected: PASS.

- [ ] **Step 5: Create module docs**

Create `modules/system-aipc-portal/README.md`:

```markdown
# system-aipc-portal

Local AIPC entry portal.

The portal lists installed/manageable AIPC services declared through `/etc/aipc/portal/services/*.yaml`. It does not manage service internals and does not special-case Mem0.

## Endpoint

`http://127.0.0.1:7080`

## Verification

- Static/render: `modules/system-aipc-portal/verify.sh` parses Python and metadata.
- Hardware: active `aipc-portal.service`, `GET /healthz`, and browser access through `aipc portal open`.
```

- [ ] **Step 6: Create package and endpoint files**

Create `modules/system-aipc-portal/packages.txt` as an empty file or with only packages already used by the base image:

```text
```

Create `modules/system-aipc-portal/env/endpoint`:

```text
http://127.0.0.1:7080
```

- [ ] **Step 7: Create portal metadata for itself**

Create `modules/system-aipc-portal/files/etc/aipc/portal/services/aipc-portal.yaml`:

```yaml
id: aipc-portal
title: AIPC Portal
module: system-aipc-portal
kind: system
systemd: aipc-portal.service
health: http://127.0.0.1:7080/healthz
endpoint: http://127.0.0.1:7080
ui: http://127.0.0.1:7080/
tags:
  - system
  - dashboard
```

- [ ] **Step 8: Create systemd unit**

Create `modules/system-aipc-portal/files/etc/systemd/system/aipc-portal.service`:

```ini
[Unit]
Description=AIPC local entry portal
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/lib/aipc-portal/aipc-portal
Environment=PYTHONPATH=/usr/lib/aipc-portal:/usr/lib/aipc-tools
Restart=on-failure

[Install]
WantedBy=default.target
```

If `/usr/lib/aipc-tools` is not where rendered `aipc_lib` lives, copy the small metadata/render helpers into the module in Step 9 and import from `aipc_portal.registry` only.

- [ ] **Step 9: Create portal package**

Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/__init__.py`:

```python
"""AIPC local entry portal."""
```

Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/registry.py`:

```python
from __future__ import annotations

from pathlib import Path

from aipc_lib.portal import ServiceMetadata, load_service_metadata, render_portal_html

SERVICES_DIR = Path("/etc/aipc/portal/services")


def load_services() -> list[ServiceMetadata]:
    return load_service_metadata(SERVICES_DIR)


def render() -> str:
    return render_portal_html(load_services())
```

Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/server.py`:

```python
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aipc_portal.registry import render

HOST = "127.0.0.1"
PORT = 7080


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, "text/plain; charset=utf-8", b"ok\n")
            return
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", render().encode("utf-8"))
            return
        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

Create `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc-portal`:

```python
#!/usr/bin/env python3
from aipc_portal.server import main

main()
```

- [ ] **Step 10: Create post-install**

Create `modules/system-aipc-portal/post-install.sh`:

```sh
#!/bin/sh
set -eu
chmod 0755 /usr/lib/aipc-portal/aipc-portal 2>/dev/null || true
systemctl enable aipc-portal.service >/dev/null 2>&1 || true
```

- [ ] **Step 11: Create verify script**

Create `modules/system-aipc-portal/verify.sh`:

```sh
#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
fail() { echo "aipc-portal: $*" >&2; exit 1; }

pkg_dir="$this_dir/files/usr/lib/aipc-portal"
[ -f "$pkg_dir/aipc_portal/server.py" ] || fail "server.py missing"
[ -f "$pkg_dir/aipc_portal/registry.py" ] || fail "registry.py missing"
[ -f "$this_dir/files/etc/aipc/portal/services/aipc-portal.yaml" ] || fail "self metadata missing"
python3 -m py_compile "$pkg_dir/aipc_portal/server.py" "$pkg_dir/aipc_portal/registry.py" || fail "python syntax error"

if ! command -v systemctl >/dev/null 2>&1 || ! systemctl is-active --quiet aipc-portal.service; then
    echo "aipc-portal: static OK (service not active; no live hardware check)" >&2
    exit 0
fi

curl -sf http://127.0.0.1:7080/healthz >/dev/null || fail "GET /healthz failed"
curl -sf http://127.0.0.1:7080/ >/dev/null || fail "GET / failed"
echo "aipc-portal: static + hardware OK"
```

- [ ] **Step 12: Make shell scripts executable**

Run:

```bash
chmod +x modules/system-aipc-portal/post-install.sh modules/system-aipc-portal/verify.sh modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc-portal
```

- [ ] **Step 13: Run targeted checks**

Run:

```bash
pytest tools/tests/test_portal.py -q
modules/system-aipc-portal/verify.sh
```

Expected: pytest PASS. `verify.sh` exits 0 with static OK wording on the dev host if the service is not installed/live.

- [ ] **Step 14: Commit**

```bash
git add modules/system-aipc-portal tools/aipc_lib/portal.py tools/tests/test_portal.py
git commit -m "feat(portal): add aipc entry portal module

Co-authored-by: gpt-5.5-high <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: aipc-portal-mem0-dashboard-2026-07-08
Spec-Task: aipc-portal-mem0-dashboard#4"
```

---

### Task 5: `aipc portal` CLI

**Files:**
- Modify: `tools/aipc_lib/portal.py`
- Modify: `tools/aipc_lib/cli.py`
- Test: `tools/tests/test_portal.py`

**Interfaces:**
- Consumes: `portal_url(endpoint_file: Path) -> str`, `portal_status(url: str) -> str`, `open_portal(url: str, runner: Callable)`.
- Produces: user commands `aipc portal` and `aipc portal open`.

- [ ] **Step 1: Add failing CLI helper tests**

Append to `tools/tests/test_portal.py`:

```python
def test_portal_url_reads_endpoint_file(tmp_path: Path) -> None:
    endpoint = tmp_path / "endpoint"
    endpoint.write_text("http://127.0.0.1:7080\n", encoding="utf-8")

    assert portal.portal_url(endpoint) == "http://127.0.0.1:7080"


def test_open_portal_uses_xdg_open() -> None:
    calls: list[list[str]] = []

    def runner(args: list[str], check: bool) -> object:
        calls.append(args)
        return object()

    portal.open_portal("http://127.0.0.1:7080", runner=runner)

    assert calls == [["xdg-open", "http://127.0.0.1:7080"]]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tools/tests/test_portal.py::test_portal_url_reads_endpoint_file tools/tests/test_portal.py::test_open_portal_uses_xdg_open -q
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 3: Implement CLI helpers**

Append to `tools/aipc_lib/portal.py`:

```python
from collections.abc import Callable
import subprocess
import urllib.request

DEFAULT_ENDPOINT_FILE = Path("modules/system-aipc-portal/env/endpoint")
INSTALLED_ENDPOINT_FILE = Path("/etc/aipc/modules/system-aipc-portal/endpoint")


def portal_url(endpoint_file: Path = DEFAULT_ENDPOINT_FILE) -> str:
    if endpoint_file.exists():
        return endpoint_file.read_text(encoding="utf-8").strip().rstrip("/")
    return "http://127.0.0.1:7080"


def portal_status(url: str) -> str:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/healthz", timeout=2) as response:
            return "running" if 200 <= response.status < 300 else "unhealthy"
    except Exception:
        return "unreachable"


def open_portal(
    url: str,
    runner: Callable[[list[str]], object] | Callable[[list[str], bool], object] = subprocess.check_call,
) -> None:
    try:
        runner(["xdg-open", url], True)  # type: ignore[misc]
    except TypeError:
        runner(["xdg-open", url])  # type: ignore[misc]
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
pytest tools/tests/test_portal.py::test_portal_url_reads_endpoint_file tools/tests/test_portal.py::test_open_portal_uses_xdg_open -q
```

Expected: PASS.

- [ ] **Step 5: Wire CLI command**

Modify `tools/aipc_lib/cli.py` following the existing argparse/subcommand pattern:

```python
from aipc_lib import portal as portal_mod
```

Add command handlers near other top-level commands:

```python
def portal_cmd() -> None:
    url = portal_mod.portal_url()
    status = portal_mod.portal_status(url)
    print(f"AIPC portal: {url} ({status})")


def portal_open_cmd() -> None:
    url = portal_mod.portal_url()
    portal_mod.open_portal(url)
    print(f"Opened AIPC portal: {url}")
```

In `main()`, add parser entries:

```python
portal_parser = subparsers.add_parser("portal", help="Show or open the AIPC entry portal")
portal_sub = portal_parser.add_subparsers(dest="portal_command")
portal_sub.add_parser("open", help="Open the AIPC entry portal in the browser").set_defaults(func=lambda _args: portal_open_cmd())
portal_parser.set_defaults(func=lambda _args: portal_cmd())
```

If existing `cli.py` uses a different handler signature, adapt only the wrapper line so it matches the current pattern.

- [ ] **Step 6: Run CLI smoke commands**

Run:

```bash
python -m aipc_lib.cli portal
python -m aipc_lib.cli portal open --help
```

Expected: first command prints `AIPC portal: http://127.0.0.1:7080 (...)`; second command prints help and does not open a browser.

- [ ] **Step 7: Run tests**

Run:

```bash
pytest tools/tests/test_portal.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/aipc_lib/portal.py tools/aipc_lib/cli.py tools/tests/test_portal.py
git commit -m "feat(cli): add aipc portal commands

Co-authored-by: gpt-5.5-high <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: aipc-portal-mem0-dashboard-2026-07-08
Spec-Task: aipc-portal-mem0-dashboard#5"
```

---

### Task 6: Official Mem0 dashboard module wiring

**Files:**
- Modify: `modules/memory-mem0/files/etc/systemd/system/aipc-mem0.service`
- Create or modify: `modules/memory-mem0/files/etc/systemd/system/aipc-mem0-dashboard.service`
- Modify: `modules/memory-mem0/files/usr/lib/aipc-mem0/requirements.txt`
- Modify: `modules/memory-mem0/post-install.sh`
- Modify: `modules/memory-mem0/verify.sh`
- Modify: `modules/memory-mem0/README.md`

**Interfaces:**
- Consumes: spike decision from Task 2.
- Produces: official Mem0 dashboard/API services if feasible, otherwise a documented blocker and no fake implementation.

- [ ] **Step 1: Stop if Task 2 found a blocker**

If `modules/memory-mem0/README.md` says `Decision: blocked`, do not edit service files. Update `openspec/changes/aipc-portal-mem0-dashboard/tasks.md` task 2 with the blocker and commit docs only.

- [ ] **Step 2: Choose one runtime path**

Use the smallest official path that works from the spike:

- If upstream Compose images support this host and local-only binding, use Quadlet or systemd-managed Podman units.
- If upstream source build is required, build/install at image build time and run via systemd.

Do not add both paths.

- [ ] **Step 3: Generate runtime secrets outside repo**

Add a root-owned runtime setup script only if upstream requires generated secrets. The script must create files under `/var/lib/aipc-mem0/` or `/etc/aipc/mem0/`, not under the repo.

Use this shell pattern in the setup script:

```sh
if [ ! -f /var/lib/aipc-mem0/jwt-secret ]; then
    umask 077
    openssl rand -base64 48 > /var/lib/aipc-mem0/jwt-secret
fi
```

- [ ] **Step 4: Wire local provider config**

Set upstream-supported environment variables so the server uses:

```text
LLM provider: OpenAI-compatible local LiteLLM
LLM base URL: http://127.0.0.1:4000/v1
LLM model: resident-small
Embedding base URL: http://127.0.0.1:4000/v1
Embedding model: embed-bge
Database: local Postgres/pgvector from db-postgres
```

Use the exact upstream variable names from Task 2. If upstream variable names differ from these labels, document the mapping in `README.md`.

- [ ] **Step 5: Keep build/runtime split**

`post-install.sh` may install files, create directories, chmod executables, and enable units. It must not start services or curl health endpoints.

- [ ] **Step 6: Update verify**

`modules/memory-mem0/verify.sh` should:

```sh
curl -sf http://127.0.0.1:8888/health >/dev/null || fail "Mem0 API health failed"
curl -sf http://127.0.0.1:3000/ >/dev/null || fail "Mem0 dashboard failed"
```

Keep a static OK path when the service is not active on the dev host.

- [ ] **Step 7: Run module verify**

Run:

```bash
modules/memory-mem0/verify.sh
```

Expected: static OK on non-installed dev host, or live OK on hardware.

- [ ] **Step 8: Commit**

```bash
git add modules/memory-mem0 openspec/changes/aipc-portal-mem0-dashboard/tasks.md
git commit -m "feat(mem0): wire official dashboard path

Co-authored-by: gpt-5.5-high <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: aipc-portal-mem0-dashboard-2026-07-08
Spec-Task: aipc-portal-mem0-dashboard#2"
```

Expected: commit only if official wiring exists or a clear blocker doc was recorded.

---

### Task 7: Render, tests, and final evidence

**Files:**
- Modify: `openspec/changes/aipc-portal-mem0-dashboard/tasks.md`
- Modify: `docs/agent-log.md`

**Interfaces:**
- Consumes: tasks 1-6 complete.
- Produces: verification evidence and agent log row.

- [ ] **Step 1: Run OpenSpec validation**

Run:

```bash
openspec validate aipc-portal-mem0-dashboard --strict
```

Expected: PASS.

- [ ] **Step 2: Run targeted Python tests**

Run:

```bash
pytest tools/tests/test_portal.py tools/tests/test_mem0_server_contract.py tools/tests/test_render_bootc.py tools/tests/test_render_ansible.py tools/tests/test_render_parity.py -q
```

Expected: PASS. If a render test requires fixture updates for the new module, update the fixture only when the failure proves the new module is missing from expected render output.

- [ ] **Step 3: Run module verifies**

Run:

```bash
modules/system-aipc-portal/verify.sh
modules/memory-mem0/verify.sh
```

Expected: static OK on dev host if services are not live; hardware OK only on the physical AI PC after deployment.

- [ ] **Step 4: Run render commands**

Run:

```bash
tools/aipc render bootc
tools/aipc render ansible --check
```

Expected: both commands succeed. If command names differ, use the existing repo-supported render commands and record the exact output.

- [ ] **Step 5: Update OpenSpec tasks**

Mark completed tasks in `openspec/changes/aipc-portal-mem0-dashboard/tasks.md`. Do not mark hardware verification complete unless actually run on the physical AI PC.

- [ ] **Step 6: Append agent log**

Append one row to `docs/agent-log.md` using the file's existing table format. Include:

```text
2026-07-08 | 副官/大哥 as appropriate | gpt-5.5-high or worker model | aipc-portal-mem0-dashboard-2026-07-08 | aipc-portal-mem0-dashboard | sha range | static/render-verified; hardware pending unless run on device
```

- [ ] **Step 7: Final commit**

```bash
git add openspec/changes/aipc-portal-mem0-dashboard/tasks.md docs/agent-log.md
git commit -m "chore(portal): record verification evidence

Co-authored-by: gpt-5.5-high <noreply@anthropic.com>
Agent-Role: 大哥
Agent-Run: aipc-portal-mem0-dashboard-2026-07-08
Spec-Task: aipc-portal-mem0-dashboard#verify"
```

Expected: commit succeeds if files changed. If no files changed, skip commit and report verification evidence.

---

## Self-Review

- Spec coverage: Task 1 covers OpenSpec; Task 2 covers official Mem0 feasibility; Task 3 covers Mem0 metadata; Task 4 covers portal module; Task 5 covers CLI; Task 6 covers official dashboard wiring; Task 7 covers validation/render/evidence.
- Placeholder scan: no deferred implementation steps are allowed; Task 6 explicitly stops on blocker rather than hiding a custom fallback.
- Type consistency: `ServiceMetadata`, `load_service_metadata`, `render_portal_html`, `portal_url`, `portal_status`, and `open_portal` are defined before use by CLI and module code.
