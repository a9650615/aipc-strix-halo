# AIPC Control Center SPA

## Why

The current portal and status dashboard present related operational data in
separate server-rendered surfaces. Operators need one local control center that
keeps the existing status and actions, shows live Z13 Flow inputs against a
simple chassis diagram, and distinguishes those device facts from AI MAX+ 395
platform telemetry.

## What Changes

- Replace the portal's document-style dashboard UI with an Astro-built SPA.
- Keep the existing localhost Python portal as the runtime API and static asset
  host; Astro is a build-time frontend dependency, not a new runtime daemon.
- Migrate all old status-dashboard data into a versioned dashboard snapshot API.
- Add a Device view with a simple first-party SVG chassis diagram, explicit
  input/I-O availability, and a bounded live event stream.
- Keep AI MAX+ 395 performance telemetry in a separate platform section of the
  same control center.

## Non-goals

- Copying ASUS code, artwork, or branding.
- A configurable Command Center button policy in this change.
- Treating absent hardware as a failure or inventing unavailable sensor values.

## Impact

- Affected modules: `system-aipc-portal`, `system-asus-input`.
- Affected tooling: `tools/aipc_lib/status_dashboard.py` migration adapter and
  its tests.
- New build dependency: Astro, used only while building portal assets.
