from __future__ import annotations

import json
from pathlib import Path

from aipc_lib import panel_mirror


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


SAMPLE_INI = """\
[Containments][365][General]
AppletOrder=366;367;368

[Containments][365][Applets][366]
plugin=org.kde.plasma.kickoff

[Containments][365][Applets][367]
plugin=org.kde.plasma.pager

[Containments][365][Applets][368]
plugin=org.kde.plasma.icontasks

[Containments][365][Applets][368][Configuration][General]
launchers=applications:systemsettings.desktop
minimizeActiveTaskOnClick=false

[Containments][372][Applets][375]
plugin=org.kde.plasma.systemtray

[Containments][372][Applets][375][General]
extraItems=org.kde.plasma.battery

[Containments][372][Applets][375][Applets][376]
plugin=org.kde.kdeconnect

[Containments][372][Applets][375][Applets][376][Configuration][General]
someInternalKey=should not leak into our capture
"""


def test_parse_ini_sections_splits_on_bracket_headers() -> None:
    sections = panel_mirror._parse_ini_sections(SAMPLE_INI)
    assert sections["Containments][365][General"]["AppletOrder"] == "366;367;368"
    assert sections["Containments][365][Applets][368"]["plugin"] == "org.kde.plasma.icontasks"
    assert (
        sections["Containments][365][Applets][368][Configuration][General"]["launchers"]
        == "applications:systemsettings.desktop"
    )


def test_capture_applet_config_gets_configuration_general_nesting() -> None:
    sections = panel_mirror._parse_ini_sections(SAMPLE_INI)
    captured = panel_mirror._capture_applet_config(sections, "365", "368")
    assert captured == {
        "Configuration][General": {
            "launchers": "applications:systemsettings.desktop",
            "minimizeActiveTaskOnClick": "false",
        }
    }


def test_capture_applet_config_gets_shallow_general_nesting() -> None:
    sections = panel_mirror._parse_ini_sections(SAMPLE_INI)
    captured = panel_mirror._capture_applet_config(sections, "372", "375")
    assert captured == {"General": {"extraItems": "org.kde.plasma.battery"}}


def test_capture_applet_config_excludes_nested_sub_applets() -> None:
    # systemtray's own child status-notifier entries (kdeconnect etc.) are
    # auto-managed from running services, not something addWidget()
    # recreates -- must not leak into the captured config.
    sections = panel_mirror._parse_ini_sections(SAMPLE_INI)
    captured = panel_mirror._capture_applet_config(sections, "372", "375")
    assert not any("Applets" in suffix for suffix in captured)


def test_capture_panel_spec_combines_widgets_and_config(tmp_path: Path) -> None:
    config_path = tmp_path / "appletsrc"
    config_path.write_text(SAMPLE_INI)

    def fake_runner(cmd, **kwargs):
        script = cmd[-1]
        if "panel.widgets()" in script:
            return _FakeCompletedProcess(stdout="365;org.kde.plasma.kickoff,366;org.kde.plasma.icontasks,368")
        return _FakeCompletedProcess(stdout="center 0 fit 466 44 true adaptive none")

    spec = panel_mirror.capture_panel_spec("bottom", 0, config_path, fake_runner)

    assert spec["geometry"] == "center 0 fit 466 44 true adaptive none"
    assert spec["widgets"][0][0] == "org.kde.plasma.kickoff"
    assert spec["widgets"][1][0] == "org.kde.plasma.icontasks"
    assert spec["widgets"][1][1] == {
        "Configuration][General": {
            "launchers": "applications:systemsettings.desktop",
            "minimizeActiveTaskOnClick": "false",
        }
    }


def test_capture_panel_spec_returns_none_when_screen_has_no_panel(tmp_path: Path) -> None:
    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(stdout="")

    assert panel_mirror.capture_panel_spec("bottom", 5, tmp_path / "appletsrc", fake_runner) is None


def _spec(widgets: list[str], geometry: str = "center 0 fit 400 44 true adaptive none") -> dict:
    return {"geometry": geometry, "widgets": [[w, {}] for w in widgets]}


def test_mirror_panels_bootstraps_to_primary_screen_on_first_run(tmp_path: Path) -> None:
    # No prior state: screen 0 (primary) has an extra widget the other
    # screen lacks. First run should adopt primary's spec everywhere,
    # not silently treat today's mismatch as the new baseline.
    calls = []
    specs = {
        0: _spec(["org.kde.plasma.kickoff", "org.kde.plasma.icontasks", "org.kde.plasma.systemmonitor"]),
        1: _spec(["org.kde.plasma.kickoff", "org.kde.plasma.icontasks"]),
    }

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "kscreen-doctor":
            return _FakeCompletedProcess(
                stdout=json.dumps(
                    {
                        "outputs": [
                            {"connected": True, "enabled": True, "priority": 1, "pos": {"x": 0, "y": 0}},
                            {"connected": True, "enabled": True, "priority": 2, "pos": {"x": 400, "y": 0}},
                        ]
                    }
                )
            )
        script = cmd[-1] if cmd[0] == "qdbus" else ""
        if "screenGeometry" in script and "primaryIdx" not in script and "idx = 0" in script:
            return _FakeCompletedProcess(stdout="0")
        if "out.push(ps[i].screen)" in script:
            return _FakeCompletedProcess(stdout="0,1")
        if "panel.widgets()" in script:
            screen = 0 if "screen === 0" in script else 1
            widget_types = [w[0] for w in specs[screen]["widgets"]]
            ref = ";".join(f"{t},{i}" for i, t in enumerate(widget_types))
            return _FakeCompletedProcess(stdout=f"{screen},panel;{ref}")
        if "old.remove()" in script:
            return _FakeCompletedProcess(stdout="99;100,101,102")
        return _FakeCompletedProcess(stdout="center 0 fit 400 44 true adaptive none")

    state_path = tmp_path / "state.json"
    config_path = tmp_path / "appletsrc"
    config_path.write_text("")

    panel_mirror.mirror_panels("bottom", state_path, config_path, fake_runner)

    rebuild_calls = [c for c in calls if c[0] == "qdbus" and "old.remove()" in c[-1]]
    assert len(rebuild_calls) == 1
    assert "screen === 1" in rebuild_calls[0][-1]
    assert json.loads(state_path.read_text())


def test_mirror_panels_noop_when_only_one_screen(tmp_path: Path) -> None:
    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(stdout="0")

    panel_mirror.mirror_panels("bottom", tmp_path / "state.json", tmp_path / "appletsrc", fake_runner)
    assert not (tmp_path / "state.json").exists()


def test_panel_mirror_unit_files_reference_resolved_aipc_path() -> None:
    units = panel_mirror.panel_mirror_unit_files("/home/birdyo/.local/bin/aipc")
    assert "PathModified=" in units["aipc-panel-mirror.path"]
    service = units["aipc-panel-mirror.service"]
    assert "ExecStart=/home/birdyo/.local/bin/aipc config preset mirror-dock" in service
    assert "ExecStart=/home/birdyo/.local/bin/aipc config preset mirror-topbar" in service


def test_install_panel_mirror_units_disables_superseded_units_and_enables_new_one(tmp_path: Path) -> None:
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    panel_mirror.install_panel_mirror_units(tmp_path, fake_runner)

    assert ["systemctl", "--user", "disable", "--now", "aipc-dock-launcher-sync.path"] in calls
    assert ["systemctl", "--user", "disable", "--now", "aipc-panel-widget-sync.path"] in calls
    assert ["systemctl", "--user", "enable", "--now", "aipc-panel-mirror.path"] in calls
    unit_dir = tmp_path / ".config/systemd/user"
    assert (unit_dir / "aipc-panel-mirror.path").exists()
    assert (unit_dir / "aipc-panel-mirror.service").exists()
