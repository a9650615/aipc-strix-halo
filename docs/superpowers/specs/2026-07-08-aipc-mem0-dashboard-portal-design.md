# AIPC Mem0 Dashboard + Entry Portal Design

## Goal

Ship an integration package that gives the AI PC a local SaaS-like management surface without building a custom Mem0 UI.

The package has two first-class AIPC modules:

1. `memory-mem0` runs the official Mem0 self-hosted server/dashboard and wires it to local AIPC services.
2. `system-aipc-portal` provides the AIPC entry portal: a local homepage listing installed manageable services and linking to their dashboards.

## Non-goals

- No custom Mem0 dashboard.
- No remote management surface.
- No cloud Mem0 SaaS dependency.
- No generic admin framework.
- No login system in v1; services bind to `127.0.0.1` only.
- No cross-module special cases in the portal.

## Architecture

```text
Browser
  |
  v
AIPC Entry Portal
127.0.0.1:<portal-port>
  |
  +-- reads /etc/aipc/portal/services/*.yaml
  |
  +-- Mem0 Memory card -----------> Official Mem0 dashboard
  |                                  127.0.0.1:<mem0-port>
  |
  +-- LiteLLM card ----------------> endpoint/status only
  +-- RAG Embedder card -----------> endpoint/status only
  +-- other module cards ----------> declared UI if present
```

## Module: `memory-mem0`

`memory-mem0` remains the memory service module, but its implementation should move from the current minimal local FastAPI wrapper to the official Mem0 self-hosted server/dashboard if the official package is usable on this platform.

Responsibilities:

- Run the official Mem0 self-hosted server/dashboard locally.
- Bind only to `127.0.0.1`.
- Wire connection information at install/runtime:
  - Postgres/pgvector: existing `db-postgres` endpoint.
  - LLM gateway: existing LiteLLM endpoint, `http://127.0.0.1:4000/v1`.
  - Default LLM model: `resident-small`.
  - Embedding endpoint: existing LiteLLM endpoint.
  - Default embedding model: `embed-bge`.
- Store generated runtime secrets outside the repo under `/var/lib/aipc-mem0/` or `/etc/aipc/mem0/`.
- Install a portal metadata file for discovery.
- Keep the existing lightweight wrapper only as a temporary fallback until the official dashboard path is verified.

`memory-mem0` must not know how the portal renders cards.

## Module: `system-aipc-portal`

`system-aipc-portal` is a new first-class AIPC module with the standard module layout:

```text
modules/system-aipc-portal/
  README.md
  packages.txt
  files/
  env/
  post-install.sh
  verify.sh
```

Responsibilities:

- Run a localhost-only entry portal web service.
- Read service declarations from `/etc/aipc/portal/services/*.yaml`.
- Show service cards with:
  - title
  - module name
  - category/kind
  - systemd unit status when declared
  - health endpoint status when declared
  - API endpoint when declared
  - UI link when declared
- Provide CLI entry points:
  - `aipc portal` prints portal status and URL.
  - `aipc portal open` opens the portal in the default browser.

The portal must not contain Mem0-specific logic. Mem0 appears because `memory-mem0` installs metadata.

## Portal service metadata contract

Each module that wants to appear in the portal installs one YAML file:

```text
/etc/aipc/portal/services/<service-id>.yaml
```

Minimum contract:

```yaml
id: mem0
title: Mem0 Memory
module: memory-mem0
kind: memory
systemd: aipc-mem0.service
health: http://127.0.0.1:7000/healthz
endpoint: http://127.0.0.1:7000
ui: http://127.0.0.1:7000/
tags:
  - memory
  - dashboard
```

Unknown keys are ignored so modules can add detail later without breaking old portals.

## Data flow

```text
module install/render
  |
  v
/etc/aipc/portal/services/*.yaml
  |
  v
system-aipc-portal reads declarations
  |
  +-- systemctl is-active <unit>
  +-- HTTP GET <health>
  +-- render card + links
```

## Verification

Static/render checks:

- `openspec validate --strict` for the selected change.
- Python syntax checks for new portal code.
- Unit/self-check for metadata parsing.
- `tools/aipc render bootc`.
- `tools/aipc render ansible --check`.
- Existing test suite for `tools/aipc` command wiring.

Module checks:

- `memory-mem0/verify.sh` checks the official Mem0 API health and dashboard HTTP response when installed.
- `system-aipc-portal/verify.sh` checks metadata parsing and portal HTTP response when installed.

Hardware verification:

- `aipc portal` prints the localhost portal URL.
- `aipc portal open` opens the portal.
- Portal shows at least itself and Mem0 when both modules are installed.
- Clicking Mem0 opens the official Mem0 dashboard.
- Mem0 dashboard can see/manage memory using the prewired local connection settings.

## Implementation notes

Start with the least code that holds:

1. Spike the official Mem0 self-hosted package in isolation.
2. If it runs on this platform, wire it into `memory-mem0`.
3. Add `system-aipc-portal` as a small localhost web app.
4. Add portal metadata files for Mem0 and the portal itself.
5. Add `aipc portal` and `aipc portal open`.

If the official Mem0 dashboard cannot run cleanly on this platform, stop and report the blocker instead of building a custom dashboard.
