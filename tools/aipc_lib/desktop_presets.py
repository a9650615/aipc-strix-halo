from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable

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


def connected_screen_count(runner: RunnerT = subprocess.run) -> int:
    result = runner(["kscreen-doctor", "-j"], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return sum(1 for o in data.get("outputs", []) if o.get("connected") and o.get("enabled"))


def ensure_panels_script(screen_count: int) -> str:
    """Plasma evaluateScript source: create a bottom Dock + top bar on every
    connected screen that doesn't already have one (idempotent -- skips
    screens that already have a matching panel), then force every bottom/top
    panel to `hiding = "autohide"`.

    autohide (not "none"/"dodgewindows") is deliberate: those other modes
    reserve permanent strut space, which squeezes fullscreen windows down to
    fit around the panel instead of letting them use the whole screen --
    hardware-verified bug report 2026-07-04. autohide fully hides the panel
    and reveals it on hover, which also means whichever screen your mouse is
    on gets its Dock back on hover -- no separate focus-follow script needed.
    """
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
ps = panels();
for (var j = 0; j < ps.length; j++) {{
  if (ps[j].location === "bottom" || ps[j].location === "top") {{
    ps[j].hiding = "autohide";
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
            "natural-scroll + tap-to-click touchpad, per-screen autohide "
            "Dock + menu bar (GZ302EA touchpad id hardcoded)"
        ),
    ),
}


def list_presets() -> list[Preset]:
    return list(PRESETS.values())


def apply_preset(name: str, runner: RunnerT = subprocess.run) -> None:
    if name not in PRESETS:
        raise KeyError(name)
    for cmd in window_buttons_mac_style_commands():
        runner(cmd, check=True)
    for cmd in touchpad_mac_style_commands():
        runner(cmd, check=True)
    screen_count = connected_screen_count(runner)
    runner(ensure_panels_command(screen_count), check=True)
    runner(reconfigure_kwin_command(), check=False)
