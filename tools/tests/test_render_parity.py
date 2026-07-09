from __future__ import annotations

from pathlib import Path

import pytest

from aipc_lib.modules import Module
from aipc_lib.render_ansible import render as render_ansible
from aipc_lib.render_bootc import render as render_bootc

# The four module subdirectories both renderers must consume. If a future
# renderer forgets one, this test fails. Upgrade path = add a case if a fifth
# subdir type is ever introduced. (ponytail: one parity test, not a per-subdir suite.)
SUBDIRS = ["files", "modprobe.d", "env", "quadlet"]


@pytest.fixture()
def full_mod(tmp_path: Path) -> Module:
    """Synthetic module with all four rendered subdirectories populated."""
    mdir = tmp_path / "mod-full"
    for sd in SUBDIRS:
        d = mdir / sd
        d.mkdir(parents=True)
        # sentinel file so each dir is non-empty
        (d / ("x" if sd != "quadlet" else "x.container")).write_text("x")
    return Module(name="mod-full", path=mdir, packages=[], kargs=[])


def test_both_renderers_reference_all_four_subdirs(full_mod: Module) -> None:
    """The two renderers must not drift: each consumes files/, modprobe.d/,
    env/, and quadlet/ from every module that has them."""
    bootc_out = render_bootc([full_mod], base="base:latest", image_ref="x", build_date="d")
    ansible_out = render_ansible([full_mod])

    # Every subdir src is referenced by both renderers.
    for sd in SUBDIRS:
        src = f"modules/mod-full/{sd}/"
        assert src in bootc_out, f"bootc render missing {sd}/"
        assert src in ansible_out, f"ansible render missing {sd}/"

    # The three distinctive destinations are referenced by both renderers
    # (files/ dest is "/" — covered by the src check above).
    for dest in [
        "/etc/modprobe.d/",
        "/etc/aipc/env.d/mod-full/",
        "/etc/containers/systemd/",
    ]:
        assert dest in bootc_out, f"bootc render missing dest {dest}"
        assert dest in ansible_out, f"ansible render missing dest {dest}"


def test_both_renderers_append_hwdb_update(tmp_path: Path) -> None:
    mdir = tmp_path / "mod-hwdb"
    hwdb_dir = mdir / "files/etc/udev/hwdb.d"
    hwdb_dir.mkdir(parents=True)
    (hwdb_dir / "x.hwdb").write_text("evdev:name:Test Device:*\n")
    mod = Module(name="mod-hwdb", path=mdir, packages=[], kargs=[])

    bootc_out = render_bootc([mod], base="base:latest", image_ref="x", build_date="d")
    ansible_out = render_ansible([mod])

    assert "systemd-hwdb update" in bootc_out
    assert "systemd-hwdb update" in ansible_out
