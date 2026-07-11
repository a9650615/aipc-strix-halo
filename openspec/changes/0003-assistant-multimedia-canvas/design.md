# design: 0003-assistant-multimedia-canvas

## Context

Portal cards currently describe services; voice overlay carries short status
text; agent responses carry text plus loosely defined artifacts. None is a
contract for agent-produced visual results. This change introduces that
contract without turning the model into a frontend code generator.

## Goals / Non-Goals

Goals:

- Show useful visual evidence as soon as it is available.
- Let agents choose an appropriate safe layout dynamically.
- Preserve source, freshness, accessibility, and text-only degradation.
- Keep network fetch, media decoding, rendering, and actions outside the model.

Non-goals are listed in the proposal and include executable UI, general GIS,
online-assistant Canvas automation, and a full gaming canvas.

## Decisions

### D1 — Artifact envelope is separate from canvas layout

**Chosen:** every produced item is an `ArtifactEnvelope`; a canvas is one
artifact kind that references media assets and sources.

**Alternatives considered:** put canvas JSON directly in `/chat`; store visual
results as Portal service cards. The first bloats chat/session payloads and the
second corrupts a service-health registry with per-turn runtime data.

```json
{
  "schema": "aipc.artifact.v1",
  "id": "uuid",
  "session_id": "uuid",
  "kind": "canvas|image|audio|video|file|text|code",
  "title": "西北太平洋颱風動態",
  "mime_type": "application/vnd.aipc.canvas+json",
  "status": "pending|ready|failed|expired",
  "created_at": "RFC3339",
  "expires_at": "RFC3339|null",
  "producer": "worker-id",
  "sensitivity": "public|personal|restricted",
  "size_bytes": 0,
  "content_ref": "sha256:...",
  "preview_ref": "sha256:...|null",
  "sources": ["source-id"]
}
```

The chat result contains only artifact ids, titles, kinds, statuses, and local
open URLs. Full manifests/content are fetched from the localhost artifact API.

### D2 — Agent generates a restricted component tree

**Chosen:** `aipc.canvas.v1` is data validated with a closed JSON Schema.
Trusted renderers own all HTML/native widgets, styles, interactions, and
accessibility behavior.

**Alternatives considered:** generated HTML/React; Markdown with embedded HTML;
fixed templates only. Executable markup is unsafe, while fixed templates cannot
adapt to weather, comparison, timeline, or gallery results.

```json
{
  "schema": "aipc.canvas.v1",
  "canvas_id": "uuid",
  "revision": 3,
  "session_id": "uuid",
  "title": "颱風動態",
  "locale": "zh-TW",
  "created_at": "RFC3339",
  "expires_at": "RFC3339|null",
  "presentation": {"preferred":"auto","theme":"system","density":"comfortable"},
  "summary": {"text":"完整文字摘要","spoken_text":"160 字內播報"},
  "layout": {"type":"stack","id":"root","children":[]},
  "assets": {},
  "sources": [],
  "actions": [],
  "policy": {"network":"cached_only","sensitivity":"public"}
}
```

Allowed containers: `stack`, `grid`, `section`, and Portal-only `tabs`.
Allowed content: `text`, `metric`, `card`, `image`, `gallery`, `timeline`,
`table`, `divider`, `source_list`, and `map_like`.

Common fields include stable `id`, `visibility`, `aria_label`,
`fallback_text`, and source references. Style values are enumerated design
tokens. Unknown node types or properties fail validation.

Document limits: 256 KiB, 80 nodes, depth 6, 24 assets, 4 KiB per text node,
12 gallery images, 30 timeline items, and 8 actions. IDs match
`[A-Za-z0-9_-]{1,64}` and are unique.

### D3 — Map-like is geometry, not arbitrary map code

**Chosen:** `map_like` contains a declared projection, bounds, optional cached
static base image, and marker/polyline/polygon/cone layers using `[lon, lat]`
coordinates and fixed style tokens.

**Alternatives considered:** embedded Leaflet/Mapbox scripts or arbitrary tile
URLs; screenshot-only maps. Scripts/tiles violate the network and executable UI
boundary, while screenshots cannot express a sourced, accessible storm track.

For a typhoon, the agent may supply current marker, observed track, forecast
track/cone, warning polygon, and timestamps. Portal renders local geometry.
Overlay uses one cached snapshot or the current/next three timeline points.

### D4 — Remote media crosses a localhost safety boundary

**Chosen:** agents submit media candidates; a low-privilege fetch/decode worker
produces a content-addressed `media_ref`. Renderers accept only `media_ref`.

**Alternatives considered:** `<img src=original_url>` or letting the agent save
files anywhere. These enable tracking pixels, SSRF, secret-bearing URLs,
unbounded downloads, and arbitrary filesystem access.

Fetcher policy:

- HTTPS by default; explicit allowlist required for HTTP.
- Resolve and revalidate every redirect; reject loopback, private, link-local,
  multicast, metadata-service, and IPv6 ULA targets; maximum three redirects.
- Separate search credentials from media fetch; never forward Authorization,
  cookies, or provider tokens.
- Stream with byte/time limits, sniff magic bytes, decode under CPU/memory/time
  limits, reject SVG/HTML/PDF masquerade and animation in v1.
- Maximum 10 MiB, 8192 pixels per side, and 25 megapixels per asset.
- Remove unnecessary EXIF/profile metadata and transcode to PNG/WebP.
- Redact secret query parameters before persisting source URLs.

### D5 — Provenance and freshness are visible

**Chosen:** every factual/media node references at least one source record with
publisher, URL, retrieval time, optional publication/capture time, hash,
license state, and trust label. Renderers show nearby source chips and a full
source list.

**Alternatives considered:** source list only at the bottom or trust the model's
caption. Neither lets the user distinguish an official current warning from an
old or unrelated image.

Typhoon canvases prefer official meteorological sources, display the last data
update prominently, and label stale/offline cache. `license=unknown` may be
shown transiently with attribution but is not retained or redistributed beyond
policy.

### D6 — Progressive immutable snapshots plus safe patches

**Chosen:** clients receive a skeleton quickly, then monotonically increasing
revisions and restricted patches; every patched document is fully revalidated.

**Alternatives considered:** wait for every image or stream arbitrary DOM
operations. Waiting hurts latency; DOM operations bypass schema security.

Events use `aipc.canvas.event.v1` with `canvas_id`, `revision`, `seq`, timestamp,
event type, and document hash:

- `canvas.created`, `canvas.patch`, `canvas.completed`, `canvas.failed`,
  `canvas.expired`
- `asset.pending`, `asset.ready`, `asset.failed`

Patches allow only add/replace/remove below layout, asset state/media metadata,
and sources. They cannot change schema or identity. Sequence gaps trigger a
snapshot refresh. Only one terminal event is accepted.

### D7 — Three renderer profiles share one document

**Chosen:** Portal, compact overlay, and deterministic text fallback consume the
same validated document.

**Alternatives considered:** ask the model to generate a separate layout/text
for every surface. That produces inconsistent facts and multiplies prompt/UI
failure modes.

- Portal: full responsive grid, gallery, timeline, table, and local map-like
  interaction.
- Overlay: one image, three cards/metrics, three timeline entries; unsupported
  nodes collapse to fallback text plus「在面板查看」.
- Text fallback: deterministically derived title, summary, key metrics/cards,
  current/next timeline entries, image alt/source annotations, and numbered
  sources. Agent-supplied fallback text is escaped and advisory.
- Voice: speaks `spoken_text` and announces the visual result; it never reads
  binary media or full canvas JSON.

### D8 — Cache is local, bounded, and lifecycle-aware

**Chosen:** content-addressed media plus an indexed artifact registry under
`/var/lib/aipc-agent/artifacts`; canvases pin referenced media until expiry.

**Alternatives considered:** home-directory downloads or unbounded permanent
cache. Both violate reproducibility, privacy, and storage hygiene.

Default caps: weather/typhoon TTL 10 minutes, news 1 hour, static reference
image 24 hours, negative fetch cache 30 seconds, total media cache 512 MiB.
HTTP cache headers may shorten but not extend policy caps. Unpinned media is LRU
evicted. Offline stale data may render only with its recorded update time and a
stale warning.

### D9 — Actions are semantic and user-initiated

**Chosen:** v1 actions are limited to `open_artifact`, `open_source`,
`refresh_artifact`, and `dismiss`, with typed ids and visible target host.

**Alternatives considered:** arbitrary URL, shell, file, custom URI, or model-
generated callback. These bypass `agent-gate` and renderer security.

No external action runs automatically. Future side effects require a separate
ExecutionGrant and a new spec delta.

### D10 — Rollout is text-first

**Chosen:** schema/text fallback first, Portal renderer second, overlay preview
third, then live media and map-like canary.

**Alternatives considered:** enable the complete visual path at once. Text-first
keeps the assistant usable while media security and hardware layout are tested.

## Security Boundary

- No `eval`, `innerHTML`, runtime script, arbitrary CSS, iframe, SVG markup,
  template expression, or remote tile/image load.
- Artifact API binds loopback, uses session-scoped unguessable access tokens,
  denies cross-origin access, and sends a restrictive CSP.
- Agent strings are plain text and escaped by renderers.
- Media decode runs outside the Portal process under resource limits.
- Original URLs, source records, and route traces never contain credentials.
- `restricted` artifacts never gain remote-media permission implicitly.

## Latency Targets

On physical Strix Halo hardware under normal load:

| Milestone | p95 target |
|---|---:|
| validated skeleton produced | 250 ms after canonical result starts |
| Portal first text/skeleton render | 400 ms |
| compact overlay render | 200 ms |
| complete layout, excluding images | 1.5 s |
| first cached image | 300 ms |
| first uncached allowlisted image | 2.5 s |
| patch validation/apply | 16 ms Portal, 8 ms overlay |

Images may finish in the background for up to 15 seconds and SHALL NOT block
`canvas.completed`. Fetch concurrency is four globally and two per host. Known
aspect ratios reserve space to keep cumulative layout shift below 0.1.

## Risks

- Agent emits malformed or hostile layout → strict schema, fixed registry,
  resource limits, deterministic fallback.
- Image URL targets internal services → per-hop DNS/IP validation and no direct
  renderer fetch.
- Old storm image appears current → visible capture/retrieval time, source link,
  TTL/stale badge, and official-source preference.
- Rich rendering delays voice → skeleton/text first; assets remain asynchronous.
- Portal becomes artifact owner → registry stays under agent runtime; Portal is
  a renderer/consumer.
- Multiple active deltas conflict at archive → tasks require rebase against the
  archived owner specs before 0003 archive.

## Migration Plan

1. Add artifact registry and schemas with text fallback only.
2. Let workers publish artifact references without changing existing text.
3. Add Portal gallery/detail renderer behind a feature flag.
4. Add overlay preview/open action.
5. Add safe remote-media fetcher, then map-like typhoon canary.
6. Enable by default only after the physical-hardware suite passes.

## Open Questions

1. Default artifact retention: recommended 24 hours for transient results and
   explicit pin for durable artifacts.
2. Initial official typhoon source allowlist: decide during implementation from
   authoritative sources reachable in the deployment region.
3. Whether Portal opens automatically for image-rich voice results: recommended
   no; show preview and let the user open it.
