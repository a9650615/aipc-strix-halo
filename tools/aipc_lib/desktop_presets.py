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
# static policy: dock is never-hide (same as the top bar), on every screen.
# (2026-07-06, two iterations: first shipped as "autohide", which
# macOS-Dock-style always hides regardless of overlap and only reveals on
# hover -- not what was wanted ("為什麼我沒有遮擋還是會隱藏"). Switched to
# "dodgewindows" (hide only when a window actually overlaps it) -- but a
# maximized window's geometry covers the dock's strip by definition, so
# double-click-to-maximize kept hiding it too, still not wanted. Landed on
# "none": same as the top bar, it reserves its own strut so ordinary window
# maximize stops short of it instead of covering it; hardware-verified this
# leaves the dock visible through maximize. A genuinely fullscreen window
# (games, video players) still overrides the strut and covers it -- that's
# the compositor's own exclusive-fullscreen behavior, unrelated to this
# per-panel `.hiding` setting.)
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

# Relative to $HOME. Tracks each Dock's last-seen launchers= value so
# reconcile_dock_launchers can tell "this screen just changed" apart from
# "everyone still matches" -- see that function's docstring.
DOCK_LAUNCHER_STATE_RELPATH = Path(".local/state/aipc/dock-launcher-sync.json")


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

    2026-07-06 update, direct user request ("dock app 項目同步", later refined
    to "哪一個 change, 就 sync 到全部的 dock"): the 07-04 spec above turned out
    too broad in practice -- a second screen's Dock with no pinned launchers
    just looks broken, not "whatever the user placed". apply_preset now
    calls reconcile_dock_launchers() as one narrow, explicit exception: it
    overwrites only the `launchers` value, propagating whichever screen's
    list changed most recently to every other screen. Everything else
    (widget list, other per-widget config) stays covered by the
    non-destructive rule above.

    Hiding policy is the one thing this DOES force on every panel, new or
    existing, every apply (setting `.hiding` never touches widgets so it
    doesn't conflict with the non-destructive rule above). Direct user spec
    2026-07-04, after the fullscreen-detecting KWin script repeatedly failed
    to work ("還是沒有解決任何問題"): "每個螢幕的 dock 都設定自動隱藏, 選單列
    永遠不隱藏就好了". Landed on "none" (same as the top bar) after two wrong
    guesses, both hardware-verified wrong by direct user report on
    2026-07-06: "autohide" always hides regardless of overlap and only
    reveals on hover ("為什麼自動隱藏現在我沒有遮擋還是會隱藏"); "dodgewindows"
    hides whenever a window overlaps it, but a maximized window's geometry
    always does, so double-click-to-maximize kept hiding it too. "none"
    reserves the dock's own strut so ordinary maximize stops short of it --
    genuinely fullscreen windows (games, video players) still cover it via
    the compositor's own exclusive-fullscreen path, independent of this
    setting. Note: the Panel scripting API silently accepts invalid
    `.hiding` string literals and falls back to "none" instead of raising --
    "windowscover" and "windowsgobelow" (natural-sounding guesses) are NOT
    valid values; "autohide", "dodgewindows" and "none" are the confirmed set.
    Every screen's Dock (bottom panel) and top bar both use "none".
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
    applySpec(p, "bottom", bottomSpec, "none");
  }}
  if (!haveTop[s]) {{
    var t = new Panel;
    t.screen = s;
    applySpec(t, "top", topSpec, "none");
  }}
}}

for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location === "bottom") ps[i].hiding = "none";
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


def all_dock_icontasks_ids_script() -> str:
    """Prints "<panelId>,<appletId>;<panelId>,<appletId>;..." for every
    screen's Dock (bottom panel) icontasks widget -- the pinned launcher
    list lives per-widget-instance, so a screen without a launchers= key
    just shows an empty Dock with no way to pin an app short of doing it by
    hand on that screen specifically. No primary/replica distinction here;
    that's for reconcile_dock_launchers to decide from state, not this."""
    return """\
var ps = panels();
var out = [];
for (var i = 0; i < ps.length; i++) {
  if (ps[i].location !== "bottom") continue;
  var widgets = ps[i].widgets();
  for (var j = 0; j < widgets.length; j++) {
    if (widgets[j].type === "org.kde.plasma.icontasks") {
      out.push(ps[i].id + "," + widgets[j].id);
    }
  }
}
print(out.join(";"));
"""


def all_dock_icontasks_ids_command() -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        all_dock_icontasks_ids_script(),
    ]


def _read_launchers(panel_id: str, applet_id: str, runner: RunnerT) -> str:
    return runner(
        [
            "kreadconfig6",
            "--file",
            "plasma-org.kde.plasma.desktop-appletsrc",
            "--group",
            "Containments",
            "--group",
            panel_id,
            "--group",
            "Applets",
            "--group",
            applet_id,
            "--group",
            "Configuration",
            "--group",
            "General",
            "--key",
            "launchers",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def reconcile_dock_launchers(state_path: Path, runner: RunnerT = subprocess.run) -> None:
    """Direct user request 2026-07-06 ("其中一個 dock 做變更, 就自動 sync 到全部
    的 dock"): whichever screen's Dock launcher list was edited since the
    last run, propagate it to every other screen's Dock. No primary/replica
    distinction -- genuinely symmetric, last-writer-wins, so it's meant to
    be triggered by a systemd path unit watching the appletsrc file (kernel
    inotify, not a hand-rolled polling loop -- see the removed
    aipc-sync-plasma.service for what that looked like and why it was torn
    out) as well as being called once from apply_preset.

    state_path holds the last-seen launchers string per panel id as JSON,
    so a run can tell "did panel X change since last time" apart from
    "everyone still matches, nothing to do" -- without that, every trigger
    (including the one caused by this function's own writes) would look
    like a change and loop forever.

    ponytail: if two docks are edited in the same interval between trigger
    runs, which one wins is arbitrary (lowest panel id) -- only matters if
    you edit two screens within the same debounce window, which a
    path-unit trigger (fires within ~seconds of the write) makes rare.
    """
    result = runner(all_dock_icontasks_ids_command(), capture_output=True, text=True, check=True)
    pairs = [tuple(ref.split(",")) for ref in result.stdout.strip().split(";") if ref]
    if len(pairs) < 2:
        return

    current = {panel_id: _read_launchers(panel_id, applet_id, runner) for panel_id, applet_id in pairs}

    previous: dict[str, str] = {}
    if state_path.exists():
        previous = json.loads(state_path.read_text())

    changed = sorted(pid for pid, value in current.items() if pid in previous and previous[pid] != value)

    if changed:
        canonical = current[changed[0]]
        for panel_id, applet_id in pairs:
            if current[panel_id] != canonical:
                runner(
                    _kwriteconfig(
                        "plasma-org.kde.plasma.desktop-appletsrc",
                        ["Containments", panel_id, "Applets", applet_id, "Configuration", "General"],
                        "launchers",
                        canonical,
                    ),
                    check=True,
                )
        current = {pid: canonical for pid in current}

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(current))


def dock_launcher_sync_unit_files(aipc_path: str) -> dict[str, str]:
    """Unit file contents keyed by filename. PathModified= is kernel inotify,
    not a hand-rolled polling loop -- see the torn-out aipc-sync-plasma.service
    (dead code, a sed/awk polling script) for what that looked like and why
    it was removed. The .service is a oneshot: one trigger, one
    reconcile_dock_launchers() run, exit."""
    return {
        "aipc-dock-launcher-sync.path": """[Unit]
Description=Watch KDE panel config for Dock launcher pin changes

[Path]
PathModified=%h/.config/plasma-org.kde.plasma.desktop-appletsrc

[Install]
WantedBy=default.target
""",
        "aipc-dock-launcher-sync.service": f"""[Unit]
Description=Reconcile Dock pinned-launcher lists across screens

[Service]
Type=oneshot
ExecStart={aipc_path} config preset sync-dock-launchers
""",
    }


def install_dock_launcher_sync_units(home: Path, runner: RunnerT = subprocess.run) -> None:
    """Direct user request 2026-07-06 ("其中一個 dock 做變更, 就自動 sync 到全部
    的 dock"): install + enable a systemd --user path unit so
    reconcile_dock_launchers runs automatically on every panel-config change,
    not only when `aipc config preset apply` is run by hand. Resolves the
    `aipc` binary's actual path at install time via shutil.which rather than
    hardcoding /usr/local/bin/aipc (the shipped-image path per commit
    11a9db9) -- a pipx dev install like this machine's lives at
    ~/.local/bin/aipc instead, and systemd user services don't inherit that
    onto PATH by default. Idempotent: re-writing identical unit files and
    re-running `enable --now` on an already-enabled unit are both no-ops."""
    aipc_path = shutil.which("aipc") or "aipc"
    unit_dir = home / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, content in dock_launcher_sync_unit_files(aipc_path).items():
        (unit_dir / name).write_text(content)
    runner(["systemctl", "--user", "daemon-reload"], check=False)
    runner(["systemctl", "--user", "enable", "--now", "aipc-dock-launcher-sync.path"], check=False)


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
            "cloned across screens, Dock (bottom panel) and top bar both "
            "reserve their space and never hide, on every screen "
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
    reconcile_dock_launchers(home / DOCK_LAUNCHER_STATE_RELPATH, runner)
    runner(reconfigure_kwin_command(), check=False)
    install_dock_launcher_sync_units(home, runner)
