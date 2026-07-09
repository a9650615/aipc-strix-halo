# codexbar-usage Specification Delta

## ADDED Requirements
### Requirement: CodexBar Usage CLI Module

The system SHALL provide a `dev-ai-codexbar-usage` module that installs an `aipc-usage` command for inspecting AI coding provider usage on Linux.

#### Scenario: CLI is importable after module install

- **WHEN** the module package is installed into the AIPC tools virtualenv
- **THEN** `python -m codexbar_usage --help` exits successfully and lists the `usage`, `cost`, `serve`, `config`, and `cache` commands

#### Scenario: Provider catalog includes core providers

- **WHEN** `codexbar_usage.registry.all_providers()` is loaded
- **THEN** the catalog contains at least the core providers Codex, Claude, OpenAI, Gemini, Copilot, OpenRouter, LiteLLM, Grok, and DeepSeek

### Requirement: CodexBar Usage HTTP Server

The system SHALL expose a localhost HTTP server through the `aipc-usage serve` command for desktop integrations.

#### Scenario: Health endpoint reports readiness

- **WHEN** `aipc-usage serve --host 127.0.0.1 --port <port>` is running
- **THEN** `GET /health` returns HTTP 200 with JSON status `ok`

#### Scenario: Usage endpoint returns JSON snapshots

- **WHEN** `GET /usage` is requested from the local server
- **THEN** the response is a JSON array of provider snapshot objects, even when providers are not configured with API keys

### Requirement: CodexBar GUI Module

The system SHALL provide a `dev-ai-codexbar-gui` module that installs a local desktop/tray client for the `aipc-usage` HTTP server.

#### Scenario: GUI can read usage from live server

- **WHEN** the usage server is running on localhost
- **THEN** the GUI usage panel fetch helper can retrieve and parse the `/usage` JSON response

### Requirement: Render Parity for CodexBar Modules

The bootc and ansible render targets SHALL both include the CodexBar usage and GUI modules when those module directories are enabled.

#### Scenario: Bootc render includes codexbar modules

- **WHEN** `aipc render bootc` renders enabled modules
- **THEN** the generated Containerfile copies and runs install steps for `dev-ai-codexbar-usage` and `dev-ai-codexbar-gui`

#### Scenario: Ansible render includes codexbar modules

- **WHEN** `aipc render ansible` renders enabled modules
- **THEN** the generated playbook copies and runs install steps for `dev-ai-codexbar-usage` and `dev-ai-codexbar-gui`
