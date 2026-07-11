# assistant-artifacts Specification Delta

## ADDED Requirements

### Requirement: Stable Local Artifact Envelope

The system SHALL represent every assistant-produced artifact with a versioned
envelope containing stable id, session id, kind, title, MIME type, status,
timestamps, producer, sensitivity, size, content/preview references, and source
references. Chat responses SHALL carry bounded references rather than binary or
large artifact content.

#### Scenario: Agent returns a typhoon canvas

- **WHEN** a worker produces a canvas and two images
- **THEN** the chat result SHALL contain artifact references and the full
  manifests/content SHALL be retrievable only from the localhost artifact API

### Requirement: Agent Layout Is Declarative And Strictly Validated

The system SHALL accept agent-generated layouts only as `aipc.canvas.v1`
documents using the closed component registry and resource limits defined by
this change. It SHALL reject unknown node/property types, invalid references,
duplicate ids, excessive size/depth/count, raw HTML/JS/CSS/SVG, and executable
expressions before any renderer consumes the document.

#### Scenario: Agent emits script in a card

- **WHEN** a canvas contains executable markup, an unknown node, or an
  over-limit tree
- **THEN** validation SHALL fail, no executable content SHALL reach a renderer,
  and the user SHALL still receive the canonical text fallback

### Requirement: Remote Media Uses Safe Content-Addressed Cache

Every remotely discovered media item SHALL pass through the localhost fetch and
decode boundary before rendering. Renderers SHALL load only validated
content-addressed media references and SHALL NOT fetch original URLs.

#### Scenario: Image resolves to private address

- **WHEN** an image URL or any redirect resolves to loopback, private,
  link-local, multicast, metadata-service, or IPv6 ULA space
- **THEN** fetch SHALL fail with a safe diagnostic and the canvas SHALL render
  its missing-image fallback without contacting the target

#### Scenario: Valid official image

- **WHEN** an allowlisted HTTPS image passes redirect, byte, MIME, decode,
  dimension, pixel, and metadata checks
- **THEN** the system SHALL transcode/store it by content hash and publish an
  `asset.ready` event containing its local media reference

### Requirement: Multimedia Provenance And Freshness Are Visible

Every factual or media node SHALL reference at least one source containing
publisher, original URL, retrieval time, optional publication/capture time,
content hash, license state, and trust label. Renderers SHALL expose sources and
mark stale cached information visibly.

#### Scenario: Cached typhoon image is stale

- **WHEN** the assistant is offline and only an expired storm image is available
- **THEN** the canvas MAY display it with its recorded update time and a clear
  stale warning and SHALL NOT present it as current

### Requirement: Canvas Progress Uses Monotonic Validated Revisions

Canvas creation and updates SHALL use monotonic revision and sequence numbers,
one terminal event, document hashes, and restricted add/replace/remove patches.
Every resulting snapshot SHALL pass full schema validation.

#### Scenario: Client misses a patch

- **WHEN** a renderer detects a sequence gap, revision rollback, or document
  hash mismatch
- **THEN** it SHALL discard incremental application and fetch the latest
  validated snapshot

### Requirement: Every Canvas Has Deterministic Fallbacks

Every canvas SHALL produce full Portal, compact overlay, deterministic text,
and spoken-summary projections from the same validated document. Unsupported
nodes and failed media SHALL degrade without losing key facts or sources.

#### Scenario: Client does not support multimedia

- **WHEN** a text-only client receives a result with a canvas artifact
- **THEN** it SHALL receive title, summary, key metrics/timeline, image alt text,
  and numbered sources without parsing layout markup

### Requirement: Artifact Lifecycle Is Local And Bounded

Artifacts SHALL be stored under the dedicated local registry, be session-bound,
carry expiry/pin state, respect sensitivity and retention policy, and release
unpinned media through bounded LRU eviction. Portal service metadata SHALL NOT
be used as artifact storage.

#### Scenario: Transient canvas expires

- **WHEN** an unpinned transient canvas reaches its expiry
- **THEN** it SHALL become `expired`, stop authorizing content access, and allow
  unreferenced cached media to be reclaimed

### Requirement: Canvas Actions Are Allow-Listed And User-Initiated

Canvas actions SHALL be limited to typed local open, source open, refresh, and
dismiss operations. No action SHALL execute automatically or contain arbitrary
shell, file, custom URI, script, or unvalidated URL behavior.

#### Scenario: User opens a source

- **WHEN** the user selects a source action
- **THEN** the UI SHALL show the destination host and require an intentional
  activation before opening it

### Requirement: Typhoon Multimedia Scenario Remains Grounded

For a typhoon-status request, the assistant SHALL prefer authoritative current
sources and MAY render observed/forecast geometry, warning regions, timeline,
and safely cached imagery. It SHALL display source and update time and SHALL NOT
invent a track, warning, or image when evidence is unavailable.

#### Scenario: Track available but image fails

- **WHEN** authoritative track data succeeds and a satellite image fetch fails
- **THEN** the canvas SHALL remain useful with sourced map-like geometry,
  timeline, text fallback, and a failed-image placeholder
