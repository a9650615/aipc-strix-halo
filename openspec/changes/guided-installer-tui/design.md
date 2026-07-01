## Context

The repository now has root entrypoints for both sides of the install flow:
`Install-AIPC-Windows.ps1` delegates to Windows no-USB staging, and
`install-aipc-linux.sh` delegates to `tools/bootstrap.sh` after the installed
Bazzite system boots. The remaining gap is user guidance: the scripts are still
bare commands, so a user cannot see the full path, prerequisites, safe choices,
and next step from one keyboard-operated flow.

## Goals / Non-Goals

**Goals:**

- Provide a keyboard-first guided menu for Windows transfer/staging and Linux bootstrap.
- Show the install journey as explicit steps with current status, blocked state,
  and next action.
- Keep destructive actions behind exact-plan confirmation and read-only checks.
- Reuse existing scripts as execution backends instead of duplicating disk or
  boot logic.
- Keep the implementation dependency-light and usable in stock Windows
  PowerShell and a vanilla Bazzite terminal.

**Non-Goals:**

- No graphical installer.
- No automatic BIOS changes, reboot from Windows, Bazzite installer disk
  selection, or rich Windows-side customization beyond basic readiness/settings
  reminders.
- No Secure Boot enablement or shim/MOK flow.
- No replacement for `tools/bootstrap.sh`; the Linux guide wraps it.
- No claim that the Strix Halo boot path works before hardware verification.

## Decisions

### D1 — Menu wizard, not a full TUI framework

Use a simple numbered keyboard menu with clear sections, status labels, and
confirm prompts. On Windows this is PowerShell `Read-Host`/console output; on
Linux this is POSIX shell prompts around the existing bootstrap script.

- Alternatives considered:
  - **Terminal UI framework** (`dialog`, `gum`, Textual, Spectre.Console) — nicer,
    but adds installation/dependency friction exactly where the installer must be
    most reliable.
  - **Bare script flags only** — smallest code, but fails the core request: the
    user still cannot see steps and choices.

### D2 — Guided root entrypoints call existing backends

The root entrypoints own guidance and step selection. Existing backend scripts
own actual work: Windows staging stays in `targets/windows/install-windows.ps1`,
and Linux bootstrap stays in `tools/bootstrap.sh`.

- Alternatives considered:
  - **Move all logic into root scripts** — easier to discover but duplicates disk
    and bootstrap logic.
  - **Leave root scripts as thin delegates** — too little guidance; users still
    need to read docs to know what is safe.

### D3 — Read-only checks are first-class menu items

The menu exposes read-only checks separately from destructive or mutating steps:
Windows preflight runs before staging; Linux guide checks it is not running from
a live installer/session before calling bootstrap where possible.

- Alternatives considered:
  - **Single "install now" option** — fewer choices, but easier to misuse.
  - **Manual checklist in README only** — no runtime防呆; easy to skip.

### D4 — One-screen journey map

Each guided entrypoint starts by showing the full journey: current side
(Windows staging or Linux bootstrap), what is automated, what remains manual,
and what will not be done automatically.

- Alternatives considered:
  - **Print only the current prompt** — terse but hides context.
  - **Long docs dump** — comprehensive but users stop reading.

## Risks / Trade-offs

- **Risk: Menu gives false confidence for unverified boot path** → Mitigation:
  Windows guide always labels boot as needs-hardware-verification and never
  auto-reboots.
- **Risk: Guidance duplicates README wording and drifts** → Mitigation: keep the
  menu text short and normative; README points to the root commands only.
- **Risk: Linux wrapper runs in the live installer by mistake** → Mitigation:
  Linux guide clearly says it is for the installed Bazzite system and asks for
  confirmation before invoking `tools/bootstrap.sh`.
- **Risk: PowerShell execution policy blocks the root script before guidance
  appears** → Mitigation: README keeps the `Unblock-File` + per-process
  `RemoteSigned` command.
