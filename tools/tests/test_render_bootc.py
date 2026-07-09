from __future__ import annotations

from pathlib import Path

import pytest

from aipc_lib.modules import Module
from aipc_lib.render_bootc import render


@pytest.fixture()
def two_mods(tmp_path: Path) -> list[Module]:
    a = tmp_path / "mod-a"
    a.mkdir()
    b = tmp_path / "mod-b"
    b.mkdir()
    return [
        Module(name="mod-a", path=a, packages=["pkg-a1", "pkg-a2"], kargs=["karg=1"]),
        Module(name="mod-b", path=b, packages=["pkg-b1"], kargs=[]),
    ]


def test_from_line(two_mods: list[Module]) -> None:
    out = render(two_mods, base="quay.io/fedora/base:41", image_ref="test", build_date="2026-01-01")
    assert out.startswith("FROM quay.io/fedora/base:41\n")


def test_env_image_ref(two_mods: list[Module]) -> None:
    out = render(two_mods, base="base:latest", image_ref="ghcr.io/me/aipc:rolling", build_date="2026-01-01")
    assert "ENV AIPC_IMAGE_REF=ghcr.io/me/aipc:rolling" in out


def test_env_build_date(two_mods: list[Module]) -> None:
    out = render(two_mods, base="base:latest", image_ref="x", build_date="2026-06-28")
    assert "ENV AIPC_BUILD_DATE=2026-06-28" in out


def test_aggregated_rpm_ostree(two_mods: list[Module]) -> None:
    out = render(two_mods, base="base:latest", image_ref="x", build_date="d")
    assert "RUN rpm-ostree install -y" in out
    assert "pkg-a1" in out
    assert "pkg-b1" in out
    # single RUN for all packages
    lines = [ln for ln in out.splitlines() if "rpm-ostree install" in ln]
    assert len(lines) == 1


def test_kargs_appended(two_mods: list[Module]) -> None:
    out = render(two_mods, base="base:latest", image_ref="x", build_date="d")
    assert "/usr/lib/bootc/kargs.d/mod-a.toml" in out
    assert 'kargs = ["karg=1"]' in out


def test_bootc_lint_at_end(two_mods: list[Module]) -> None:
    out = render(two_mods, base="base:latest", image_ref="x", build_date="d")
    assert out.rstrip().endswith("RUN bootc container lint")


def test_aipc_cli_installed(two_mods: list[Module]) -> None:
    out = render(two_mods, base="base:latest", image_ref="x", build_date="d")
    assert "COPY tools/ /usr/lib/aipc/tools/" in out
    assert "pip install --no-cache-dir /usr/lib/aipc/tools" in out
    assert "ln -sf /usr/lib/aipc/tools/.venv/bin/aipc /usr/bin/aipc" in out


def test_hwdb_update_appended_when_hwdb_present(tmp_path: Path) -> None:
    m = tmp_path / "mod-hwdb"
    hwdb_dir = m / "files/etc/udev/hwdb.d"
    hwdb_dir.mkdir(parents=True)
    (hwdb_dir / "x.hwdb").write_text("evdev:name:Test Device:*\n")

    out = render([Module(name="mod-hwdb", path=m, packages=[], kargs=[])], base="base:latest", image_ref="x", build_date="d")

    assert "RUN systemd-hwdb update" in out
