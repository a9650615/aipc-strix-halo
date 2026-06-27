from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from aipc_lib.modules import Module, discover


@pytest.fixture()
def mod_root(tmp_path: Path) -> Path:
    m = tmp_path / "modules" / "test-pkg"
    m.mkdir(parents=True)
    (m / "packages.txt").write_text(
        textwrap.dedent("""\
            # comment
            rocm-smi
            amd-smi

            git
        """)
    )
    (m / "kargs.conf").write_text(
        textwrap.dedent("""\
            # kernel args
            amdgpu.gttsize=125000
            iommu=pt
        """)
    )
    return tmp_path / "modules"


def test_discover_returns_module(mod_root: Path) -> None:
    mods = discover(mod_root)
    assert len(mods) == 1
    m = mods[0]
    assert isinstance(m, Module)
    assert m.name == "test-pkg"
    assert m.packages == ["rocm-smi", "amd-smi", "git"]


def test_discover_kargs(mod_root: Path) -> None:
    mods = discover(mod_root)
    assert mods[0].kargs == ["amdgpu.gttsize=125000", "iommu=pt"]


def test_discover_no_packages_txt(tmp_path: Path) -> None:
    (tmp_path / "modules" / "empty-mod").mkdir(parents=True)
    mods = discover(tmp_path / "modules")
    assert mods[0].packages == []
    assert mods[0].kargs == []


def test_discover_skips_files(tmp_path: Path) -> None:
    root = tmp_path / "modules"
    root.mkdir()
    (root / "not-a-dir.txt").write_text("skip me")
    (root / "real-mod").mkdir()
    mods = discover(root)
    assert len(mods) == 1
    assert mods[0].name == "real-mod"
