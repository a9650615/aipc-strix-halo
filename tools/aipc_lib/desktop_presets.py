from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

KWIN_SCRIPT_ID = "focused-screen-panels"

_METADATA_JSON = """{
    "KPackageStructure": "KWin/Script",
    "KPlugin": {
        "Authors": [{"Name": "aipc"}],
        "Description": "Shows the Dock/top bar only on the currently focused screen; even that screen hides them while a window on it is truly fullscreen",
        "Icon": "preferences-system-windows-script-test",
        "Id": "focused-screen-panels",
        "License": "MIT",
        "Name": "Focused Screen Panels"
    },
    "X-Plasma-API": "javascript"
}
"""

# Three bugs, three wrong fixes, this is the fourth and correct one (2026-07-04):
#   1. hiding="none"/"dodgewindows" reserve strut space, so a truly
#      fullscreen window gets squeezed down to fit around the panel instead
#      of using the whole screen.
#   2. hiding="autohide" on *every* panel fixes (1) but now the Dock/top bar
#      disappear even on a screen with no fullscreen window at all.
#   3. Only autohiding the *active* screen while fullscreen (leaving other
#      screens' panels untouched) fixed (2) but never re-hid the
#      *unfocused* screens at all, since nothing ever set them back to
#      autohide -- both screens' Docks stayed visible permanently. The user
#      explicitly wants only the focused screen's Dock/top bar shown, the
#      rest hidden.
# The fix has to touch *every* panel on *every* recheck: the focused
# screen's panels are visible unless its window is truly fullscreen (in
# which case autohide, per bug 1/2); every other screen's panels are always
# autohide. Plasma's built-in panel visibility modes have no single option
# for any of this (the closest, "Windows Can Cover", was removed in Plasma 6:
# https://discuss.kde.org/t/windows-can-cover-panel-can-we-have-it-back-in-plasma-6/15706),
# hence the KWin script.
#
# Screen identity is matched by array position between KWin's workspace.screens
# and Plasma's panels() `.screen` index -- the only correlation the two separate
# scripting APIs (KWin JS vs Plasma Shell JS) expose. If a screen is
# unplugged/replugged in a different order the mapping can drift until KWin
# restarts.
_MAIN_JS = """\
function findOutputIndex(output) {
    var screens = workspace.screens;
    for (var i = 0; i < screens.length; i++) {
        if (screens[i] === output) {
            return i;
        }
    }
    return 0;
}

function applyAllPanels(activeIdx, activeFullScreen) {
    var script =
        "var ps = panels();" +
        "for (var i = 0; i < ps.length; i++) {" +
        "  var p = ps[i];" +
        "  if (p.location === 'bottom' || p.location === 'top') {" +
        "    if (p.screen === " + activeIdx + ") {" +
        "      p.hiding = " + (activeFullScreen ? "'autohide'" : "'none'") + ";" +
        "    } else {" +
        "      p.hiding = 'autohide';" +
        "    }" +
        "  }" +
        "}";
    callDBus("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell", "evaluateScript", script);
}

function recheck(window) {
    if (!window || !window.output) {
        return;
    }
    applyAllPanels(findOutputIndex(window.output), !!window.fullScreen);
}

function trackWindow(window) {
    if (!window || !window.fullScreenChanged) {
        return;
    }
    window.fullScreenChanged.connect(function () {
        recheck(window);
    });
}

workspace.windowActivated.connect(recheck);
workspace.windowAdded.connect(trackWindow);

if (workspace.activeWindow) {
    recheck(workspace.activeWindow);
}
"""

# GZ302EA-specific: this repo targets one fixed hardware model (CLAUDE.md §6),
# so hardcoding this exact touchpad's libinput vendor/product id follows the
# same pattern as other hardware-specific workarounds already in this repo
# (amdgpu.dcdebugmask, GPP0/GPP1 wake fix) rather than being a portability
# shortcut.
TOUCHPAD_VENDOR = "2821"
TOUCHPAD_PRODUCT = "6704"
TOUCHPAD_NAME = "ASUSTeK Computer Inc. GZ302EA-Keyboard Touchpad"

RunnerT = Callable[..., subprocess.CompletedProcess]


def _kwriteconfig(file: str, groups: list[str], key: str, value: str) -> list[str]:
    cmd = ["kwriteconfig6", "--file", file]
    for g in groups:
        cmd += ["--group", g]
    cmd += ["--key", key, value]
    return cmd


def window_buttons_mac_style_commands() -> list[list[str]]:
    """Close/minimize/maximize on the left, Mac order (close, minimize, maximize)."""
    return [
        _kwriteconfig("kwinrc", ["org.kde.kdecoration2"], "ButtonsOnLeft", "XIA"),
        _kwriteconfig("kwinrc", ["org.kde.kdecoration2"], "ButtonsOnRight", ""),
    ]


def touchpad_mac_style_commands() -> list[list[str]]:
    """Tap-to-click + natural scrolling. NOTE: libinput properties only take
    effect after logout/login, not live -- a KDE/KWin limitation, not
    something this can force from the CLI."""
    groups = ["Libinput", TOUCHPAD_VENDOR, TOUCHPAD_PRODUCT, TOUCHPAD_NAME]
    return [
        _kwriteconfig("kcminputrc", groups, "NaturalScroll", "true"),
        _kwriteconfig("kcminputrc", groups, "TapToClick", "true"),
    ]


def dock_follow_focus_enable_command() -> list[str]:
    return [
        "kwriteconfig6",
        "--file",
        "kwinrc",
        "--group",
        "Plugins",
        "--key",
        f"{KWIN_SCRIPT_ID}Enabled",
        "true",
    ]


def install_kwin_script(home: Path) -> None:
    script_root = home / ".local/share/kwin/scripts" / KWIN_SCRIPT_ID
    code_dir = script_root / "contents/code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (script_root / "metadata.json").write_text(_METADATA_JSON)
    (code_dir / "main.js").write_text(_MAIN_JS)


def connected_screen_count(runner: RunnerT = subprocess.run) -> int:
    result = runner(["kscreen-doctor", "-j"], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return sum(1 for o in data.get("outputs", []) if o.get("connected") and o.get("enabled"))


def ensure_panels_script(screen_count: int) -> str:
    """Plasma evaluateScript source: create a bottom Dock + top bar on every
    connected screen that doesn't already have one (idempotent -- skips
    screens that already have a matching panel), defaulting new panels to
    `hiding = "autohide"`. focused-screen-panels.kwinscript then makes the
    currently focused screen's panels visible (unless its window is truly
    fullscreen), keeping every other screen's panels autohidden."""
    return f"""\
var screenCount = {screen_count};
var ps = panels();
var haveBottom = {{}}, haveTop = {{}};
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location === "bottom") haveBottom[ps[i].screen] = true;
  if (ps[i].location === "top") haveTop[ps[i].screen] = true;
}}
for (var s = 0; s < screenCount; s++) {{
  if (!haveBottom[s]) {{
    var p = new Panel;
    p.screen = s; p.location = "bottom"; p.alignment = "center"; p.offset = 0;
    p.lengthMode = "fit"; p.height = 44; p.floating = true; p.opacity = "adaptive";
    p.hiding = "autohide";
    p.addWidget("org.kde.plasma.kickoff");
    p.addWidget("org.kde.plasma.pager");
    p.addWidget("org.kde.plasma.icontasks");
    p.addWidget("org.kde.plasma.marginsseparator");
    p.addWidget("org.kde.plasma.folder");
  }}
  if (!haveTop[s]) {{
    var t = new Panel;
    t.screen = s; t.location = "top"; t.alignment = "center";
    t.lengthMode = "fill"; t.height = 30; t.floating = false; t.opacity = "translucent";
    t.hiding = "autohide";
    t.addWidget("org.kde.plasma.digitalclock");
    t.addWidget("org.kde.plasma.showdesktop");
    t.addWidget("org.kde.plasma.systemtray");
    t.addWidget("org.kde.plasma.battery");
    t.addWidget("org.kde.plasma.panelspacer");
  }}
}}
"""


def ensure_panels_command(screen_count: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        ensure_panels_script(screen_count),
    ]


def reconfigure_kwin_command() -> list[str]:
    return ["qdbus", "org.kde.KWin", "/KWin", "reconfigure"]


@dataclass
class Preset:
    name: str
    description: str


PRESETS: dict[str, Preset] = {
    "mac": Preset(
        name="mac",
        description=(
            "macOS-like KDE Plasma desktop: window buttons on the left, "
            "natural-scroll + tap-to-click touchpad, Dock + menu bar shown "
            "only on the focused screen (autohidden elsewhere, and even "
            "there while fullscreen) (GZ302EA touchpad id hardcoded)"
        ),
    ),
}


def list_presets() -> list[Preset]:
    return list(PRESETS.values())


def apply_preset(name: str, home: Path, runner: RunnerT = subprocess.run) -> None:
    if name not in PRESETS:
        raise KeyError(name)
    for cmd in window_buttons_mac_style_commands():
        runner(cmd, check=True)
    for cmd in touchpad_mac_style_commands():
        runner(cmd, check=True)
    install_kwin_script(home)
    runner(dock_follow_focus_enable_command(), check=True)
    screen_count = connected_screen_count(runner)
    runner(ensure_panels_command(screen_count), check=True)
    runner(reconfigure_kwin_command(), check=False)
