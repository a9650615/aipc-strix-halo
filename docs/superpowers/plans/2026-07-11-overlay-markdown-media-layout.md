# Overlay markdown + image/text layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render assistant replies in the Qt overlay as markdown (not plain text) and lay out extracted images as a grid with source captions.

**Architecture:** Two module-level pure helpers in `aipc_voice_overlay.py` do the text work (markdown→HTML via Qt's built-in `QTextDocument.setMarkdown`, and media extraction/stripping); `_AnswerBody.set_body` calls them; `_AnswerBody.set_images` gets a 2-column grid + per-image host caption. Images are still fetched only through the existing safe `_ImageFetch`.

**Tech Stack:** Python 3, PySide6 (already a dependency), stdlib `re`/`html`.

## Global Constraints

- No new dependency (CLAUDE.md §8) — `QTextDocument.setMarkdown` ships with PySide6.
- Renderer never fetches an agent-supplied URL from the text widget; only `_ImageFetch` fetches (SSRF/tracking safety).
- Plain-text replies must render visually unchanged.
- Logic that can be pure must be module-level pure functions so it is unit-testable headless.
- File to modify: `modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py`.
- Test file: `tools/tests/test_overlay_markdown.py`.
- Commit trailers per CLAUDE.md §11 (`Co-authored-by`, `Agent-Role`, `Agent-Run`).

---

### Task 1: Pure helpers — media extraction + markdown→HTML

**Files:**
- Modify: `modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py` (add two module-level functions near `_extract_image_urls`, ~line 493)
- Test: `tools/tests/test_overlay_markdown.py`

**Interfaces:**
- Consumes: existing `_extract_image_urls(text, *, limit=6) -> list[str]`.
- Produces:
  - `_extract_and_strip_media(text: str, extra: list[str] | None = None) -> tuple[str, list[str]]`
  - `_markdown_to_html(text: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tools/tests/test_overlay_markdown.py
import importlib.util, os, sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[2]
OVL = REPO / "modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py"

def _load():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    loader = SourceFileLoader("aipc_voice_overlay", str(OVL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod

def _mod():
    pytest.importorskip("PySide6")
    return _load()

def test_extract_and_strip_markdown_image():
    m = _mod()
    clean, urls = m._extract_and_strip_media("see ![cat](https://x.test/c.png) here")
    assert urls == ["https://x.test/c.png"]
    assert "https://x.test/c.png" not in clean
    assert "see" in clean and "here" in clean

def test_extract_merges_explicit_and_dedupes():
    m = _mod()
    clean, urls = m._extract_and_strip_media(
        "a https://x.test/p.jpg b", extra=["https://x.test/p.jpg"]
    )
    assert urls == ["https://x.test/p.jpg"]

def test_markdown_bold_and_list_render_html():
    m = _mod()
    html = m._markdown_to_html("**hi**\n\n- one\n- two")
    assert "<" in html
    low = html.lower()
    assert ("font-weight" in low) or ("<b" in low) or ("<strong" in low)
    assert "one" in html and "two" in html

def test_markdown_empty_is_empty():
    m = _mod()
    assert m._markdown_to_html("   ") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tools/tests/test_overlay_markdown.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute '_extract_and_strip_media'`)

- [ ] **Step 3: Add the helpers**

Insert after `_extract_image_urls` (near line 523, before `class _ImageFetch`):

```python
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)")


def _extract_and_strip_media(text, extra=None):
    """Return (text_without_image_refs, ordered_unique_image_urls).

    Pulls markdown ![](url) and bare image URLs so they render in the safe
    gallery instead of as raw text. Non-image links are left in the text.
    """
    s = text or ""
    urls: list[str] = []

    def _add(u: str) -> None:
        u = (u or "").strip().strip("<>")
        if u and u not in urls:
            urls.append(u)

    for u in extra or []:
        _add(u)

    def _sub(m: "re.Match") -> str:
        _add(m.group(1))
        return ""

    s = _MD_IMG_RE.sub(_sub, s)
    for u in _extract_image_urls(re.sub(r"<[^>]+>", " ", s)):
        _add(u)
    for u in urls:
        s = s.replace(u, "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s, urls


def _markdown_to_html(text):
    """Markdown -> Qt rich-text HTML via QTextDocument (built into PySide6).

    Falls back to escaped plain text on empty/parse failure — never raises."""
    s = (text or "").strip()
    if not s:
        return ""
    try:
        from PySide6.QtGui import QTextDocument

        doc = QTextDocument()
        doc.setMarkdown(s)
        html = doc.toHtml()
        if html and "<" in html:
            return html
    except Exception:
        pass
    import html as _h

    return _h.escape(s).replace("\n", "<br>")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tools/tests/test_overlay_markdown.py -q`
Expected: PASS (4 passed), or SKIPPED if PySide6 absent in this env.

- [ ] **Step 5: Commit**

```bash
git add tools/tests/test_overlay_markdown.py modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py
git commit -m "feat(overlay): markdown + media-extract helpers

Co-authored-by: claude-opus-4-8 <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: overlay-markdown-media-2026-07-11"
```

---

### Task 2: Render markdown in the answer body

**Files:**
- Modify: `aipc_voice_overlay.py` — `_AnswerBody.__init__` (~line 631) and `_AnswerBody.set_body` (~lines 678, 700-706)

**Interfaces:**
- Consumes: `_extract_and_strip_media`, `_markdown_to_html` (Task 1).

- [ ] **Step 1: Force rich-text format on the label**

In `_AnswerBody.__init__`, right after `self._label = QLabel("")`:

```python
        self._label.setTextFormat(Qt.TextFormat.RichText)
```

- [ ] **Step 2: Use the helpers in `set_body`**

Replace `self._label.setText(text or "")` (line ~678) with nothing here, and replace the image block (lines ~700-706):

```python
        # was: urls = list(image_urls or []); if not urls: ... _extract_image_urls ...
        clean, urls = _extract_and_strip_media(text or "", image_urls)
        self._label.setText(_markdown_to_html(clean))
        self.set_images(urls, width=width)
        return self.measure_content_height(width)
```

(Delete the now-duplicate `self._label.setText(...)` earlier in the method and the old auto-extract block so text is set exactly once, from `clean`.)

- [ ] **Step 3: Import sanity + regression**

Run: `QT_QPA_PLATFORM=offscreen python -c "import importlib.util,os; os.environ['QT_QPA_PLATFORM']='offscreen'; from importlib.machinery import SourceFileLoader; SourceFileLoader('m','modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py').load_module(); print('import OK')"`
Expected: `import OK` (or a clean skip if PySide6 absent).
Run: `python -m pytest tools/tests/test_overlay_markdown.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py
git commit -m "feat(overlay): render reply body as markdown

Co-authored-by: claude-opus-4-8 <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: overlay-markdown-media-2026-07-11"
```

---

### Task 3: Image gallery — 2-column grid + source caption

**Files:**
- Modify: `aipc_voice_overlay.py` — `_AnswerBody.__init__` gallery layout (~line 647), `set_images` (~lines 719-759), `_on_img_ok` width (~line 773), `measure_content_height` gallery sum (~lines 823-836)
- Test: `tools/tests/test_overlay_markdown.py` (add `_source_host` test)

**Interfaces:**
- Produces: `_source_host(url: str) -> str` (module-level pure helper).

- [ ] **Step 1: Write the failing test for the caption helper**

```python
def test_source_host():
    m = _mod()
    assert m._source_host("https://www.cwa.gov.tw/V8/C/x.png") == "cwa.gov.tw"
    assert m._source_host("not a url") == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tools/tests/test_overlay_markdown.py::test_source_host -q`
Expected: FAIL (no `_source_host`).

- [ ] **Step 3: Add `_source_host` and switch the gallery to a grid**

Add near the other helpers:

```python
def _source_host(url):
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""
```

In `__init__`, change the gallery layout from `QVBoxLayout` to `QGridLayout`:

```python
        self._gal = QGridLayout(self._gallery)
        self._gal.setContentsMargins(0, 4, 0, 0)
        self._gal.setSpacing(8)
```

In `set_images`, place two per row and size each to half width when there is
more than one image (replace the `self._gal.addWidget(lab)` and the width `w`
used for the label):

```python
        cols = 2 if len(urls[:max_n]) > 1 else 1
        cell_w = max(120, (w - (cols - 1) * 8) // cols)
        for i, url in enumerate(urls[:max_n]):
            # ... build `lab` exactly as before, but:
            lab.setFixedWidth(cell_w)
            # ...
            self._gal.addWidget(lab, i // cols, i % cols)
            # keep: self._img_labels.append(lab); self._img_urls.append(url); self._fetcher.fetch(gen, url)
        self._gal_cols = cols
        self._gal_cell_w = cell_w
        self.measure_content_height(w + 10)
```

In `_on_img_ok`, scale to the cell width and append the host caption as the
label text under the pixmap is not possible on one QLabel; set the host as the
label tooltip already exists — add a visible caption by setting the label's
accessible text and a bottom-aligned host via a small suffix is out of scope for
one QLabel, so set the host as the tooltip AND keep the pixmap (caption row is a
follow-up). Replace `w = max(100, lab.width() or self._inner_w)` with:

```python
        w = max(100, getattr(self, "_gal_cell_w", 0) or lab.width() or self._inner_w)
```

In `measure_content_height`, sum the gallery by ROWS (max height per row of
`cols`), replacing the per-label vertical sum (lines ~824-833):

```python
        gal_h = 0
        if self._img_labels:
            cols = getattr(self, "_gal_cols", 1)
            row_h = 0
            for i, lab in enumerate(self._img_labels):
                lh = lab.height() if (lab.pixmap() is not None and not lab.pixmap().isNull()) else max(56, lab.minimumHeight())
                row_h = max(row_h, lh)
                if i % cols == cols - 1:
                    gal_h += row_h + 8
                    row_h = 0
            if row_h:
                gal_h += row_h + 8
            self._gallery.setFixedWidth(w)
            self._gallery.setFixedHeight(max(0, gal_h))
            self._gallery.show()
        else:
            self._gallery.setFixedHeight(0)
            self._gallery.hide()
```

- [ ] **Step 4: Run tests + import sanity**

Run: `python -m pytest tools/tests/test_overlay_markdown.py -q`
Expected: PASS.
Run the import-sanity command from Task 2 Step 3. Expected: `import OK`.

- [ ] **Step 5: Commit**

```bash
git add modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py tools/tests/test_overlay_markdown.py
git commit -m "feat(overlay): 2-col image grid + source host

Co-authored-by: claude-opus-4-8 <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: overlay-markdown-media-2026-07-11"
```

---

### Task 4: Render parity + module verify + agent-log

**Files:**
- Verify only; Modify: `docs/agent-log.md` (one row)

- [ ] **Step 1: ruff + module verify**

Run: `ruff check modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py tools/tests/test_overlay_markdown.py`
Run: `sh modules/voice-pipecat/verify.sh; echo rc=$?`
Expected: ruff clean; verify rc=0.

- [ ] **Step 2: Render parity**

Run: `python -m aipc_lib.cli render bootc --image-ref ghcr.io/x/aipc:test --build-date 2026-07-11 && python -m aipc_lib.cli render ansible`
Expected: both write their generated targets without error.

- [ ] **Step 3: Append agent-log row and commit**

Add one row to `docs/agent-log.md` (date 2026-07-11, 副官, claude-opus-4-8, run `overlay-markdown-media-2026-07-11`, summary: markdown rendering + 2-col image grid in the overlay answer body; render-verified; Qt visual pending live desktop confirm).

```bash
git add docs/agent-log.md
git commit -m "docs(agent-log): overlay markdown + media layout

Co-authored-by: claude-opus-4-8 <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: overlay-markdown-media-2026-07-11"
```

- [ ] **Step 4: Hardware handoff note**

Tell the user: restart the overlay on the live desktop (`aipc voice overlay start` or the user unit) and confirm a markdown+image reply renders formatted text + a 2-column image grid; a plain reply looks unchanged. Only this step is hardware-verified; everything above is static/render-verified.

## Self-Review notes

- Spec coverage: markdown rendering (Task 1-2), image-text layout grid + source (Task 3), safe fetch unchanged (Task 3 keeps `_ImageFetch`), fallbacks (Task 1 `_markdown_to_html` escape path), non-goals untouched (no canvas/SPA/agent-contract changes). ✓
- The source-caption *visual row* is deliberately reduced to a tooltip/host in Task 3 to avoid per-image widget nesting; a visible caption row under each image is a follow-up if the user wants it (noted, not silently dropped).
- Types consistent: `_extract_and_strip_media`, `_markdown_to_html`, `_source_host`, `_gal_cols`, `_gal_cell_w` used consistently across tasks.
