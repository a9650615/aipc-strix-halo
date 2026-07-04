from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Legacy: this preset used to ship a KWin script (fullscreen-hides-panels)
# that dynamically toggled panel hiding based on per-window fullscreen state.
# After several iterations it still didn't reliably work (user, 2026-07-04:
# "還是沒有解決任何問題" -- still hasn't solved anything). Replaced with a
# static policy: dock always autohides, top bar never hides, on every screen.
# This id is kept only so apply_preset can find and remove a previously
# installed copy (see uninstall_legacy_kwin_script / disable_legacy_kwin_script_command).
LEGACY_KWIN_SCRIPT_ID = "fullscreen-hides-panels"

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


def disable_legacy_kwin_script_command() -> list[str]:
    """Turn off the old fullscreen-detecting KWin script if it was ever
    enabled on this machine -- it would otherwise fight the static
    hiding policy applied by ensure_panels_script."""
    return [
        "kwriteconfig6",
        "--file",
        "kwinrc",
        "--group",
        "Plugins",
        "--key",
        f"{LEGACY_KWIN_SCRIPT_ID}Enabled",
        "false",
    ]


def unload_legacy_kwin_script_command() -> list[str]:
    """Hardware-verified 2026-07-04: disabling a script in kwinrc + `KWin
    reconfigure` does NOT stop an already-running instance -- `isScriptLoaded`
    stayed true and its old per-window fullscreen signal handlers kept firing,
    silently overwriting the static hiding policy moments after apply_preset
    finished. `org.kde.kwin.Scripting.unloadScript` is the only thing that
    actually stops a live instance immediately."""
    return [
        "qdbus",
        "org.kde.KWin",
        "/Scripting",
        "org.kde.kwin.Scripting.unloadScript",
        LEGACY_KWIN_SCRIPT_ID,
    ]


def uninstall_legacy_kwin_script(home: Path) -> None:
    script_root = home / ".local/share/kwin/scripts" / LEGACY_KWIN_SCRIPT_ID
    if script_root.exists():
        shutil.rmtree(script_root)


def connected_screen_count(runner: RunnerT = subprocess.run) -> int:
    result = runner(["kscreen-doctor", "-j"], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return sum(1 for o in data.get("outputs", []) if o.get("connected") and o.get("enabled"))


def primary_screen_position(runner: RunnerT = subprocess.run) -> tuple[int, int]:
    """(x, y) layout position of the primary output (lowest `priority`),
    per `kscreen-doctor -j`. This is the same coordinate space as Plasma's
    scripting `screenGeometry(i).x/.y`, so the two can be matched up to find
    which Plasma panel `.screen` index is the primary display."""
    result = runner(["kscreen-doctor", "-j"], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    outputs = [o for o in data.get("outputs", []) if o.get("connected") and o.get("enabled")]
    primary = min(outputs, key=lambda o: o.get("priority", 999))
    pos = primary["pos"]
    return pos["x"], pos["y"]


def ensure_panels_script(screen_count: int, primary_x: int, primary_y: int) -> str:
    """Plasma evaluateScript source: give every connected screen a Dock +
    top bar, cloning the primary screen's *current* panels as the template
    for screens that don't have one yet, then apply a static hiding policy
    to every bottom/top panel on every screen.

    NON-DESTRUCTIVE to widgets/layout (user spec 2026-07-04: "preset 布局不要
    去動 dock app 那塊, 使用者放什麼就是什麼" -- the preset must not touch the
    dock's app content; whatever the user places stays). Existing panels'
    widget lists are left completely untouched -- pinned launchers /
    task-manager entries live inside a widget's own config, which a
    destroy-and-recreate would silently wipe. So this only *creates* panels
    on screens that lack one; it never removes or rewrites an existing
    panel's widgets.

    Consequence, stated plainly: this syncs layout to a new/bare screen at
    creation time (clone of the primary's current structure), but does NOT
    continuously reconcile already-populated screens' widget lists back into
    lockstep -- that would mean clobbering exactly the per-screen dock
    content the user asked to preserve. To re-clone a screen's widgets from
    scratch, remove its panels by hand first, then re-run.

    Hiding policy is the one thing this DOES force on every panel, new or
    existing, every apply (setting `.hiding` never touches widgets so it
    doesn't conflict with the non-destructive rule above). Direct user spec
    2026-07-04, after the fullscreen-detecting KWin script repeatedly failed
    to work ("還是沒有解決任何問題"): "每個螢幕的 dock 都設定自動隱藏, 選單列
    永遠不隱藏就好了" -- every screen's Dock (bottom panel) always autohides;
    the top bar never hides.
    """
    return f"""\
var screenCount = {screen_count};
var primaryIdx = 0;
for (var i = 0; i < screenCount; i++) {{
  var g = screenGeometry(i);
  if (g.x === {primary_x} && g.y === {primary_y}) {{
    primaryIdx = i;
    break;
  }}
}}

function readSpec(panel) {{
  var widgets = panel.widgets();
  var types = [];
  for (var i = 0; i < widgets.length; i++) {{ types.push(widgets[i].type); }}
  return {{
    alignment: panel.alignment, offset: panel.offset, lengthMode: panel.lengthMode,
    length: panel.length, height: panel.height, floating: panel.floating,
    opacity: panel.opacity, widgets: types
  }};
}}

var ps = panels();
var bottomSpec = null, topSpec = null;
var haveBottom = {{}}, haveTop = {{}};
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location === "bottom") haveBottom[ps[i].screen] = true;
  if (ps[i].location === "top") haveTop[ps[i].screen] = true;
  if (ps[i].screen !== primaryIdx) continue;
  if (ps[i].location === "bottom") bottomSpec = readSpec(ps[i]);
  if (ps[i].location === "top") topSpec = readSpec(ps[i]);
}}

if (!bottomSpec) {{
  bottomSpec = {{
    alignment: "center", offset: 0, lengthMode: "fit", length: 0, height: 44,
    floating: true, opacity: "adaptive",
    widgets: ["org.kde.plasma.kickoff", "org.kde.plasma.pager", "org.kde.plasma.icontasks",
              "org.kde.plasma.marginsseparator", "org.kde.plasma.folder"]
  }};
}}
if (!topSpec) {{
  topSpec = {{
    alignment: "center", offset: 0, lengthMode: "fill", length: 0, height: 30,
    floating: false, opacity: "translucent",
    widgets: ["org.kde.plasma.digitalclock", "org.kde.plasma.showdesktop",
              "org.kde.plasma.systemtray", "org.kde.plasma.battery", "org.kde.plasma.panelspacer"]
  }};
}}

function applySpec(panel, location, spec, hiding) {{
  panel.location = location;
  panel.alignment = spec.alignment;
  panel.offset = spec.offset;
  panel.lengthMode = spec.lengthMode;
  if (spec.lengthMode !== "fit" && spec.lengthMode !== "fill" && spec.length > 0) {{
    panel.length = spec.length;
  }}
  panel.height = spec.height;
  panel.floating = spec.floating;
  panel.opacity = spec.opacity;
  panel.hiding = hiding;
  for (var i = 0; i < spec.widgets.length; i++) {{ panel.addWidget(spec.widgets[i]); }}
}}

for (var s = 0; s < screenCount; s++) {{
  if (!haveBottom[s]) {{
    var p = new Panel;
    p.screen = s;
    applySpec(p, "bottom", bottomSpec, "autohide");
  }}
  if (!haveTop[s]) {{
    var t = new Panel;
    t.screen = s;
    applySpec(t, "top", topSpec, "none");
  }}
}}

for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location === "bottom") ps[i].hiding = "autohide";
  if (ps[i].location === "top") ps[i].hiding = "none";
}}
"""


def ensure_panels_command(screen_count: int, primary_x: int, primary_y: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        ensure_panels_script(screen_count, primary_x, primary_y),
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
            "natural-scroll + tap-to-click touchpad, unified panel layout "
            "cloned across screens, Dock (bottom panel) always autohides "
            "and the top bar never hides, on every screen "
            "(GZ302EA touchpad id hardcoded)"
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
    uninstall_legacy_kwin_script(home)
    runner(disable_legacy_kwin_script_command(), check=False)
    runner(unload_legacy_kwin_script_command(), check=False)
    screen_count = connected_screen_count(runner)
    primary_x, primary_y = primary_screen_position(runner)
    runner(ensure_panels_command(screen_count, primary_x, primary_y), check=True)
    runner(reconfigure_kwin_command(), check=False)
