# proposal: 0003-assistant-multimedia-canvas

## Why

The assistant can currently speak or return short text, but researched answers
often contain information that is inherently visual: typhoon tracks, satellite
images, warning areas, charts, product comparisons, screenshots, maps, and
timelines. Returning only a URL or describing an image makes the assistant feel
less capable than the agent that actually gathered the evidence.

Allowing an agent to emit arbitrary HTML, JavaScript, CSS, remote image URLs, or
desktop UI commands would solve presentation at the cost of code execution,
tracking pixels, SSRF, credential leakage, inconsistent layouts, and a UI that
breaks whenever a model improvises. The product needs a declarative multimedia
artifact contract: the agent chooses from safe components and supplies data;
trusted renderers own pixels, behavior, accessibility, and degradation.

## What Changes

- Introduce capability **`assistant-artifacts`** for stable artifact identity,
  lifecycle, local storage, provenance, media safety, and a versioned dynamic
  canvas document.
- Let agents return artifact references alongside text instead of embedding
  binary media or large layout payloads in chat responses.
- Define `aipc.canvas.v1`, a strictly validated component tree supporting text,
  metrics, cards, images, galleries, timelines, tables, source lists, and a
  restricted map-like visualization suitable for typhoon tracks.
- Add a localhost media fetch/cache boundary. Renderers never fetch an agent-
  supplied URL directly.
- Add progressive canvas events so text/skeleton appears first and images arrive
  without blocking the answer.
- Add Portal full rendering and voice-overlay compact rendering with a
  deterministic text fallback.
- Preserve source, publisher, retrieval/update time, content hash, and license
  state for facts and media.

## Capabilities

### New Capabilities

- `assistant-artifacts`: session-bound multimedia artifacts and safe dynamic
  canvas documents rendered from declarative data rather than executable UI.

### Modified Capabilities

- `agent-runtime`: workers publish canonical artifact references and progressive
  artifact events.
- `aipc-portal`: provides artifact gallery/detail surfaces and the full canvas
  renderer, separate from service-health cards.
- `voice-streaming`: announces artifact availability and exposes a compact
  preview/open action without putting media into the voice status file.

## Non-Goals

- Arbitrary agent-generated HTML, JavaScript, CSS, Markdown-with-HTML, iframe,
  SVG markup, browser extension, or executable widget code.
- Replacing a GIS/weather service or claiming meteorological authority.
- Automatically opening external URLs or executing actions from a canvas.
- Editing full documents, collaborative whiteboards, or ChatGPT Canvas import
  in v1; online-assistant import/export can be a later adapter.
- Making gaming overlay a full multimedia canvas in v1.
- Persisting third-party images forever when license or retention policy does
  not permit it.

## Impact

- Primary modules: `agent-orchestrator`, `system-aipc-portal`, and
  `voice-pipecat`. No new module category is introduced.
- Runtime state uses a dedicated artifact registry under
  `/var/lib/aipc-agent/artifacts/`; it does not reuse Portal service metadata.
- Remote media fetch adds a controlled network surface requiring SSRF, decode,
  cache, provenance, and resource-limit verification.
- The initial hardware scenario is a Mandarin typhoon-status query producing a
  sourced track/timeline plus at least one safely cached image.
- Automatic rendering stays disabled until static, render, and physical-hardware
  tests pass. Text answers remain available throughout rollout.
