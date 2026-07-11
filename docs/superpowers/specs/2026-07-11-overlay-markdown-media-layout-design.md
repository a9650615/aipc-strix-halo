# Voice overlay: markdown + image/text layout

Date: 2026-07-11
Scope: medium (markdown rendering + composite image/text layout in the Qt
overlay answer body). NOT the full `0003-assistant-multimedia-canvas`.

## Problem

The voice assistant overlay (`aipc_voice_overlay.py`, PySide6) renders each
reply body as **plain text** via `QLabel.setText(text)`, so markdown the model
emits (`**bold**`, headings, lists, `[links]`, code) shows literally. Images
already work — `_extract_image_urls` + async `_ImageFetch` → a gallery — but the
gallery is a crude vertical stack of up to 4 images below the text. Replies that
are inherently formatted or media-rich look worse than the content the agent
gathered.

The full declarative canvas (`0003-assistant-multimedia-canvas`, `aipc.canvas.v1`)
is the long-term answer but is a large, security-gated, hardware-verified effort.
This change is the near-term, bounded improvement to the existing overlay body.

## Approach

Use Qt's built-in `QTextDocument.setMarkdown()` (ships with PySide6 — **no new
dependency**, satisfies CLAUDE.md §8) to convert markdown → Qt rich-text HTML,
then keep feeding the existing `QLabel`. This preserves the current layout,
height-measurement, scrolling, and link handling. Rejected alternative:
replacing `QLabel` with `QTextBrowser` — more native markdown but forces a
rewrite of `measure_content_height` and scroll integration (larger blast radius,
higher regression risk) for no user-visible gain.

Images are never fetched by the text widget (avoids SSRF / tracking-pixel /
remote-load surprises, consistent with 0003's "renderers never fetch an
agent-supplied URL directly" principle). All image URLs — markdown `![](url)`,
bare image URLs — are extracted, **removed from the text**, and routed through
the existing safe `_ImageFetch` gallery.

## Components (all within `_AnswerBody` in `aipc_voice_overlay.py`)

Two new pure, unit-testable helpers (module-level, no Qt objects) so logic is
verifiable headless:

- `extract_media(text) -> (clean_text, image_urls)`: pull markdown image syntax
  and bare image URLs (reuse `_extract_image_urls` rules), return the text with
  image syntax stripped plus the ordered de-duplicated URL list.
- `markdown_to_html(text) -> str`: convert markdown to Qt rich-text HTML via
  `QTextDocument.setMarkdown().toHtml()`; on empty/parse failure return the
  original text HTML-escaped (current plain behaviour). Guarded so a bad input
  never raises into the render path.

`set_body()` changes:
1. `clean, urls = extract_media(text)` (merge with any explicit `image_urls`).
2. `self._label.setText(markdown_to_html(clean))`.
3. `self.set_images(urls, width=...)` (unchanged fetch path).

Gallery (`set_images`) layout upgrade:
- Vertical stack → responsive grid: 2 columns when body width allows, 1 when
  narrow. Keep max-N (`AIPC_OVERLAY_MAX_IMAGES`) and max-height caps.
- Optional source caption under each image: the URL's host (e.g. `cwa.gov.tw`),
  small muted text, for provenance at a glance.

## Fallbacks & invariants

- Non-markdown plain text renders visually unchanged (setMarkdown of plain text
  is near-identity; escape path covers parse failure).
- Safe async image fetch, max-N, link-open, and the `done`-card flow are
  unchanged.
- Markdown scope: bold/italic, headings (scaled for the compact HUD), ordered/
  unordered lists, links, inline code, code blocks (monospace), blockquotes,
  simple tables. No raw HTML passthrough from the model.

## Verification tiers

- Static: unit tests for `extract_media` and `markdown_to_html` (headless — no
  Qt display needed; `QTextDocument` works without a running event loop / can be
  guarded/skipped if Qt import unavailable in CI). ruff clean; module imports.
- Render-verified: `voice-pipecat` `verify.sh` + bootc/ansible parity.
- Hardware-verified (AI PC, user): overlay restarted on the live desktop; a
  markdown-and-image reply renders formatted text + image grid + source
  captions; plain replies look unchanged.

## Non-goals

- The `aipc.canvas.v1` declarative component tree, artifact registry, media
  cache boundary, progressive canvas events (all `0003`).
- Control Center SPA response rendering.
- Changing the reply data contract from the agent (still text + URLs).
