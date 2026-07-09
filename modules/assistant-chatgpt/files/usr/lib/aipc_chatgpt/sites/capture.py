"""Screen/region capture → image path for site upload pack."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def capture_fullscreen(dest: Path | None = None) -> Path:
    path = dest or Path(tempfile.mkstemp(suffix=".png", prefix="aipc-cap-")[1])
    # Prefer grim (wayland) then import/spectacle
    if _which("grim"):
        subprocess.run(["grim", str(path)], check=True)
        return path
    if _which("gnome-screenshot"):
        subprocess.run(["gnome-screenshot", "-f", str(path)], check=True)
        return path
    if _which("import"):
        subprocess.run(["import", "-window", "root", str(path)], check=True)
        return path
    raise RuntimeError("no screenshot tool (grim/gnome-screenshot/import)")


def capture_region(dest: Path | None = None) -> Path:
    path = dest or Path(tempfile.mkstemp(suffix=".png", prefix="aipc-cap-")[1])
    if _which("grim") and _which("slurp"):
        geo = subprocess.check_output(["slurp"], text=True).strip()
        subprocess.run(["grim", "-g", geo, str(path)], check=True)
        return path
    if _which("gnome-screenshot"):
        subprocess.run(["gnome-screenshot", "-a", "-f", str(path)], check=True)
        return path
    # fallback full
    return capture_fullscreen(path)


def _which(name: str) -> bool:
    from shutil import which

    return which(name) is not None
