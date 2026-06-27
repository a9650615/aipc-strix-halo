from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def _read_lines(path: Path) -> list[str]:
    """Return non-blank, non-comment lines from a text file."""
    if not path.exists():
        return []
    return [
        line
        for raw in path.read_text().splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]


@dataclass
class Module:
    name: str
    path: Path
    packages: list[str] = field(default_factory=list)
    kargs: list[str] = field(default_factory=list)


def discover(root: Path) -> list[Module]:
    """Return one Module per subdirectory of *root*, sorted by name."""
    mods: list[Module] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        mods.append(
            Module(
                name=entry.name,
                path=entry,
                packages=_read_lines(entry / "packages.txt"),
                kargs=_read_lines(entry / "kargs.conf"),
            )
        )
    return mods
