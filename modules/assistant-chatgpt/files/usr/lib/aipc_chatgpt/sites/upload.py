"""Generic file upload helper for site packs (shared engine)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def attach_file(page: Any, path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    # Common patterns: input[type=file] near composer
    loc = page.locator('input[type="file"]').first
    if loc.count() == 0:
        # try plus menu then file input
        plus = page.locator('[data-testid="composer-plus-btn"]').first
        if plus.count():
            plus.click(timeout=3000)
            page.wait_for_timeout(400)
        loc = page.locator('input[type="file"]').first
    if loc.count() == 0:
        raise RuntimeError("no file input found on page")
    loc.set_input_files(str(p))
    page.wait_for_timeout(800)
    return f"attached {p.name}"
