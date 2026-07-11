# tasks: 0003-assistant-multimedia-canvas

## 0. Contract and active-change gates

- [ ] 0.1 Freeze `aipc.artifact.v1`, `aipc.canvas.v1`, source, asset, action,
  event, patch, renderer-profile, and error JSON Schemas.
- [ ] 0.2 Resolve/rebase active `agent-runtime`, `aipc-portal`, and
  `voice-streaming` owner changes before archive; do not archive conflicting
  deltas by order accident.
- [ ] 0.3 Confirm default 24-hour transient retention, explicit pin behavior,
  and no-auto-open visual policy with the user.
- [ ] 0.4 Select initial authoritative typhoon data/image sources and document
  availability, attribution/license, update cadence, and region reachability.

## 1. Artifact registry and schemas

- [ ] 1.1 Add local artifact registry, atomic manifest/content writes, stable
  ids, lifecycle, expiry/pin, bounded references, and session access checks.
- [ ] 1.2 Implement strict canvas/source/asset/action/event validators with all
  document/node/depth/string/asset/action limits.
- [ ] 1.3 Implement deterministic text and spoken projections independent of
  agent-supplied prose fallback.
- [ ] 1.4 Add artifact list/get/snapshot/media endpoints bound to loopback with
  scoped access tokens, CSP, CORS denial, and safe cache headers.

## 2. Safe media pipeline

- [ ] 2.1 Implement candidate submission and low-privilege fetch/decode worker.
- [ ] 2.2 Enforce HTTPS/allowlist, per-hop DNS/IP/redirect SSRF checks, credential
  separation, time/byte/dimension/pixel limits, MIME sniffing, and format reject.
- [ ] 2.3 Strip unnecessary metadata, transcode to PNG/WebP, content-hash, index,
  pin, TTL, negative-cache, and LRU-evict media.
- [ ] 2.4 Add stale/offline and provenance/license behavior.

## 3. Agent and event integration

- [ ] 3.1 Extend canonical worker results with bounded artifact references.
- [ ] 3.2 Add monotonic canvas/asset event stream, restricted patches, hash/seq
  recovery, one terminal event, and cancellation semantics.
- [ ] 3.3 Add a constrained local layout-generation prompt/schema mode; reject
  invalid documents and preserve the text answer.
- [ ] 3.4 Add typhoon composition from sourced track/warning data, timeline, and
  safely fetched imagery; never synthesize missing evidence as live data.

## 4. Portal renderer

- [ ] 4.1 Add artifact list/preview/detail UI separate from service cards.
- [ ] 4.2 Implement the fixed component registry and responsive renderer for all
  v1 nodes, including local map-like geometry without external scripts/tiles.
- [ ] 4.3 Add accessibility, source/update/stale/license UI, loading skeletons,
  failed-media fallback, and local semantic actions.
- [ ] 4.4 Enforce CSP/no-innerHTML/no-eval and snapshot/security tests.

## 5. Voice and compact overlay

- [ ] 5.1 Add bounded artifact metadata to voice UX without binary/full canvas.
- [ ] 5.2 Implement overlay profile caps: one image, three cards/metrics, three
  timeline entries, deterministic fallback, and open-in-Portal action.
- [ ] 5.3 Ensure spoken summary, preview failure, barge-in, and task cancellation
  follow 0002's single-TTS-owner and separate-cancel contracts.

## 6. Static and security verification

- [ ] 6.1 Schema golden/property/fuzz tests: every node, unknown fields,
  duplicate/dangling ids, limits, NaN/coordinate bounds, revision/seq/hash.
- [ ] 6.2 Media adversarial tests: HTML/SVG/script/data/file/javascript URLs,
  MIME mismatch, bombs, EXIF, redirects to private/metadata IP, DNS rebinding,
  credential URL redaction, slow/large bodies.
- [ ] 6.3 Renderer snapshots: Portal/overlay/text across wide/narrow/HiDPI,
  zh-TW/English/RTL, long text, missing/stale media, map/timeline/gallery/table.
- [ ] 6.4 Cache tests: TTL, hit, miss, 304, negative cache, pin, expiry, LRU,
  quota, offline stale, and deduplication.
- [ ] 6.5 `npx -y @fission-ai/openspec validate
  0003-assistant-multimedia-canvas --strict`.

## 7. Render verification

- [ ] 7.1 Run `tools/aipc render bootc` and inspect artifact/runtime/Portal/voice
  files in the generated image.
- [ ] 7.2 Run `tools/aipc render ansible --check` and render-parity tests.

## 8. (AI PC) Hardware verification

- [ ] 8.1 Run the typhoon E2E: current authoritative data plus imagery produces
  skeleton, track/cone/warning/timeline, asset-ready update, source/update UI,
  spoken summary, and compact overlay.
- [ ] 8.2 Repeat with image 404, slow image, stale offline cache, invalid layout,
  sequence gap, and Portal restart; text/track/timeline remain usable.
- [ ] 8.3 Measure p50/p95 skeleton, Portal/overlay first render, complete layout,
  cached/uncached image, patch apply, memory, cache, and layout shift.
- [ ] 8.4 Verify no original remote media URL is requested by Portal/overlay and
  SSRF/CSP/resource limits hold on the physical deployment.
- [ ] 8.5 Keep multimedia default off until hardware evidence is recorded; text
  responses remain the rollback path.

## 9. Archive

- [ ] 9.1 Rebase deltas against the then-archived owner specs and re-run strict
  validation before archive.
- [ ] 9.2 Archive only after 0002 routing/result references and the required
  agent/Portal/voice owner changes are complete; gaming/online adapters remain
  separate follow-up changes.
