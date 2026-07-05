from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from aipc_lib.desktop_presets import RunnerT, _kwriteconfig, connected_screen_count, primary_screen_position

# Direct user request 2026-07-06: "類似於 mac 的 preset, 跟 sync mirror 是兩件
# 不同事情" / "一個是手動套用一次 一個是 sync 服務" -- desktop_presets.py's
# apply_preset() is a one-shot "set the look" operation (window buttons,
# touchpad, initial panel creation), run by hand via `aipc config preset
# apply mac`. This module is the other thing: a standing background
# reconciler, triggered by a systemd --user path unit, that mirrors a
# screen's ENTIRE Dock/top-bar structure (widget list + order + every
# widget's own config) onto every other screen whenever one of them
# changes. No primary/replica distinction -- whichever screen was edited
# most recently wins, symmetrically, same "last-writer-wins" model as
# desktop_presets.reconcile_widget_config (which this supersedes for actual
# use -- that function only mirrors a single named config key on an
# already-matching widget list; this mirrors the whole panel, widget
# additions/removals included, which is what "本來就應該通用...跟 Mac 一樣的
# 體驗" turned out to actually require).
#
# Known gap, confirmed 2026-07-06 by reading KDE's actual source (not just
# guessing method names), not fixable from this module: the panel-editor
# toolbar's "建立面板複本" (Clone Panel) button calls
# PanelView::clonePanelTo() -> ShellCorona::clonePanelTo()
# (KDE/plasma-workspace shell/panelview.cpp, shell/shellcorona.cpp) --
# a completely different C++ class from WorkspaceScripting::Panel
# (shell/scripting/panel.h), which is the ONLY thing `panels()` in
# evaluateScript ever returns. That scripting wrapper class has no
# duplicate/clone method at all (confirmed by reading its full header) --
# it isn't hidden, it's a deliberately narrower API surface than PanelView,
# and PanelView/ShellCorona are never bridged to the D-Bus scripting
# interface. There is no way to reach clonePanelTo from evaluateScript.
#
# Why the native clone doesn't have this module's staleness problem:
# ShellCorona::clonePanelTo copies the OLD containment's entire KConfigGroup
# into the NEW one (KConfigGroup::copyTo, in-process, before creating a
# single applet), *then* calls createApplet() for each widget -- config
# exists before the widget's QML ever initializes, so it reads correct
# values on its first paint. This module (like anything driven through
# evaluateScript) can only call addWidget() -- which creates the widget
# with defaults immediately -- and write real config afterward via
# kwriteconfig6, once the widget already exists. That ordering, not a
# missing API call, is why some widgets (a systemmonitor's chosen sensor,
# a popup's remembered size) don't visually reflect this module's write
# until something forces a full re-init (plasmashell restart). It is a
# structural limit of the scripting API, confirmed from KDE's own source,
# not a gap in this implementation.
#
# Practical takeaway: when perfect fidelity matters more than automatic
# sync, do it by hand once via the native button (enter panel edit mode ->
# panel settings toolbar -> 建立面板複本 -> drag the clone to the target
# screen) -- that path alone gets the config-before-create ordering right.
# This mirror then keeps that result in sync for whatever changes next.

APPLETSRC_RELPATH = Path(".config/plasma-org.kde.plasma.desktop-appletsrc")
DOCK_MIRROR_STATE_RELPATH = Path(".local/state/aipc/dock-mirror.json")
TOPBAR_MIRROR_STATE_RELPATH = Path(".local/state/aipc/topbar-mirror.json")


def _parse_ini_sections(text: str) -> dict[str, dict[str, str]]:
    """KDE's ini format nests groups as literal "][" inside a single
    bracketed header (e.g. "[Containments][365][Applets][368][General]") --
    stripping just the outermost brackets and using the rest as an opaque
    section name (rather than a real nested-dict parse) is enough to
    round-trip it faithfully, and sidesteps configparser's assumptions
    (interpolation, duplicate-section handling) that don't apply here."""
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        line = line.strip("\n")
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        sections[current][key] = value
    return sections


def _capture_applet_config(
    sections: dict[str, dict[str, str]], panel_id: str, applet_id: str
) -> dict[str, dict[str, str]]:
    """Every config sub-group under this applet, keyed by its suffix path
    (e.g. "Configuration][General" or just "General" -- systemtray's
    extraItems live one level shallower than icontasks' launchers, and this
    captures either without needing to know that in advance). Excludes
    nested sub-applets (systemtray's own child status-notifier entries,
    "...][Applets][376..." under the systemtray applet) -- those are
    auto-managed by the widget itself from running services, not something
    addWidget() recreates or that we should try to clone."""
    prefix = f"Containments][{panel_id}][Applets][{applet_id}]["
    captured: dict[str, dict[str, str]] = {}
    for name, kv in sections.items():
        if not name.startswith(prefix) or not kv:
            continue
        suffix = name[len(prefix) :]
        if suffix.startswith("Applets]["):
            continue
        captured[suffix] = dict(kv)
    return captured


def _read_appletsrc_sections(config_path: Path) -> dict[str, dict[str, str]]:
    if not config_path.exists():
        return {}
    return _parse_ini_sections(config_path.read_text())


def panel_widgets_script(location: str, screen: int) -> str:
    """Prints "<panelId>;<type1>,<id1>;<type2>,<id2>;..." in on-screen visual
    order (AppletOrder, not widgets() creation order -- see
    ensure_panels_script's own readSpec() for why those differ) for the
    given screen's panel at <location>, or nothing if that screen has none."""
    return f"""\
var ps = panels();
var panel = null;
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].screen === {screen} && ps[i].location === "{location}") panel = ps[i];
}}
if (!panel) {{ print(""); }}
else {{
  var widgets = panel.widgets();
  var byId = {{}};
  for (var i = 0; i < widgets.length; i++) {{ byId[widgets[i].id] = widgets[i].type; }}
  panel.currentConfigGroup = ["General"];
  var order = panel.readConfig("AppletOrder", "").split(";");
  var out = [];
  for (var i = 0; i < order.length; i++) {{
    if (byId[order[i]] !== undefined) out.push(byId[order[i]] + "," + order[i]);
  }}
  print(panel.id + ";" + out.join(";"));
}}
"""


def panel_widgets_command(location: str, screen: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        panel_widgets_script(location, screen),
    ]


def panel_geometry_script(location: str, screen: int) -> str:
    """Prints panel.{alignment,offset,lengthMode,length,height,floating,
    opacity,hiding} space-separated, or nothing if that screen has no panel
    at <location>."""
    return f"""\
var ps = panels();
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].screen === {screen} && ps[i].location === "{location}") {{
    var p = ps[i];
    print(p.alignment+" "+p.offset+" "+p.lengthMode+" "+p.length+" "+p.height+" "+p.floating+" "+p.opacity+" "+p.hiding);
  }}
}}
"""


def panel_geometry_command(location: str, screen: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        panel_geometry_script(location, screen),
    ]


def screens_with_panel_script(location: str) -> str:
    """Prints comma-separated screen indices that currently have a panel at
    <location>."""
    return f"""\
var ps = panels();
var out = [];
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location === "{location}") out.push(ps[i].screen);
}}
print(out.join(","));
"""


def screens_with_panel_command(location: str) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        screens_with_panel_script(location),
    ]


def primary_screen_index_script(screen_count: int, primary_x: int, primary_y: int) -> str:
    return f"""\
var idx = 0;
for (var i = 0; i < {screen_count}; i++) {{
  var g = screenGeometry(i);
  if (g.x === {primary_x} && g.y === {primary_y}) {{ idx = i; break; }}
}}
print(idx);
"""


def primary_screen_index_command(screen_count: int, primary_x: int, primary_y: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        primary_screen_index_script(screen_count, primary_x, primary_y),
    ]


def primary_screen_index(runner: RunnerT = subprocess.run) -> int:
    screen_count = connected_screen_count(runner)
    primary_x, primary_y = primary_screen_position(runner)
    result = runner(
        primary_screen_index_command(screen_count, primary_x, primary_y), capture_output=True, text=True, check=True
    )
    return int(result.stdout.strip() or 0)


def capture_panel_spec(
    location: str, screen: int, config_path: Path, runner: RunnerT = subprocess.run
) -> dict | None:
    """{"geometry": "...", "widgets": [[type, {suffix: {key: value}}], ...]}
    for the given screen's panel at <location>, or None if it has none."""
    widgets_out = runner(
        panel_widgets_command(location, screen), capture_output=True, text=True, check=True
    ).stdout.strip()
    if not widgets_out:
        return None
    panel_id, _, rest = widgets_out.partition(";")
    refs = [tuple(r.split(",")) for r in rest.split(";") if r]

    geometry = runner(
        panel_geometry_command(location, screen), capture_output=True, text=True, check=True
    ).stdout.strip()

    sections = _read_appletsrc_sections(config_path)
    widgets = [
        [widget_type, _capture_applet_config(sections, panel_id, applet_id)] for widget_type, applet_id in refs
    ]
    return {"geometry": geometry, "widgets": widgets}


def rebuild_panel_script(location: str, screen: int, widget_types: list[str], geometry: str) -> str:
    alignment, offset, length_mode, length, height, floating, opacity, hiding = geometry.split(" ")
    widgets_json = json.dumps(widget_types)
    return f"""\
var ps = panels();
var old = null;
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].screen === {screen} && ps[i].location === "{location}") old = ps[i];
}}
if (old) old.remove();
var p = new Panel;
p.screen = {screen};
p.location = "{location}";
p.alignment = "{alignment}";
p.offset = {offset};
p.lengthMode = "{length_mode}";
if ("{length_mode}" !== "fit" && "{length_mode}" !== "fill" && {length} > 0) p.length = {length};
p.height = {height};
p.floating = {floating};
p.opacity = "{opacity}";
p.hiding = "{hiding}";
var order = {widgets_json};
var ids = [];
for (var i = 0; i < order.length; i++) {{
  var w = p.addWidget(order[i]);
  ids.push(w.id);
}}
print(p.id + ";" + ids.join(","));
"""


def rebuild_panel_command(location: str, screen: int, widget_types: list[str], geometry: str) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        rebuild_panel_script(location, screen, widget_types, geometry),
    ]


def apply_panel_spec(location: str, screen: int, spec: dict, runner: RunnerT = subprocess.run) -> None:
    """Destroy (if present) and recreate the given screen's panel at
    <location> to match spec, restoring each widget's captured config
    verbatim under its new applet id."""
    widget_types = [w[0] for w in spec["widgets"]]
    result = runner(
        rebuild_panel_command(location, screen, widget_types, spec["geometry"]),
        capture_output=True,
        text=True,
        check=True,
    )
    panel_id, _, ids_str = result.stdout.strip().partition(";")
    new_ids = ids_str.split(",") if ids_str else []
    for (widget_type, config), new_applet_id in zip(spec["widgets"], new_ids):
        for suffix, kv in config.items():
            # suffix uses "][" as a literal separator (see _parse_ini_sections);
            # split back into individual group names the same way it was joined.
            groups = ["Containments", panel_id, "Applets", new_applet_id, *suffix.split("][")]
            for key, value in kv.items():
                runner(_kwriteconfig("plasma-org.kde.plasma.desktop-appletsrc", groups, key, value), check=True)


def mirror_panels(
    location: str,
    state_path: Path,
    config_path: Path,
    runner: RunnerT = subprocess.run,
) -> None:
    """Whichever screen's <location> panel (Dock or top bar) changed --
    widget list, order, or any widget's own config -- since the last run,
    clone it onto every other screen with a panel at that location. Fully
    symmetric: no primary/replica distinction.

    state_path holds each screen's last-seen spec (as JSON text) so a run
    can tell "this screen just changed" apart from "everyone still
    matches" -- without that, this function's own writes (from the
    previous run) would look like a fresh change and loop forever.

    ponytail: if two screens are edited in the same interval between
    trigger runs, which one wins is arbitrary (lowest screen index) -- only
    matters if you edit two screens within the same debounce window, which
    a path-unit trigger (fires within ~seconds of a write) makes rare.
    """
    screens_out = runner(screens_with_panel_command(location), capture_output=True, text=True, check=True).stdout
    screens = sorted({int(s) for s in screens_out.strip().split(",") if s})
    if len(screens) < 2:
        return

    current = {screen: capture_panel_spec(location, screen, config_path, runner) for screen in screens}
    current_json = {screen: json.dumps(spec, sort_keys=True) for screen, spec in current.items()}

    first_run = not state_path.exists()
    previous: dict[str, str] = {}
    if not first_run:
        previous = json.loads(state_path.read_text())

    if first_run:
        # No established parity to compare against yet. Rather than
        # silently adopting today's (possibly divergent) per-screen state
        # as the new baseline, use the primary screen as the one-time seed
        # -- same convention ensure_panels_script already uses for cloning
        # onto a bare screen. Purely a bootstrap default: every run after
        # this one is fully symmetric, last-writer-wins, no primary bias.
        canonical_screen = primary_screen_index(runner)
        if canonical_screen not in screens:
            canonical_screen = screens[0]
    else:
        changed = sorted(
            screen
            for screen, value in current_json.items()
            if str(screen) in previous and previous[str(screen)] != value
        )
        canonical_screen = changed[0] if changed else None

    if canonical_screen is not None:
        canonical_spec = current[canonical_screen]
        for screen in screens:
            if screen != canonical_screen and current_json[screen] != current_json[canonical_screen]:
                apply_panel_spec(location, screen, canonical_spec, runner)
        current_json = {screen: current_json[canonical_screen] for screen in screens}

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({str(k): v for k, v in current_json.items()}))


def mirror_dock(home: Path = Path.home(), runner: RunnerT = subprocess.run) -> None:
    mirror_panels("bottom", home / DOCK_MIRROR_STATE_RELPATH, home / APPLETSRC_RELPATH, runner)


def mirror_topbar(home: Path = Path.home(), runner: RunnerT = subprocess.run) -> None:
    mirror_panels("top", home / TOPBAR_MIRROR_STATE_RELPATH, home / APPLETSRC_RELPATH, runner)


def panel_mirror_unit_files(aipc_path: str) -> dict[str, str]:
    return {
        "aipc-panel-mirror.path": """[Unit]
Description=Watch KDE panel config for Dock/top-bar structural changes

[Path]
PathModified=%h/.config/plasma-org.kde.plasma.desktop-appletsrc

[Install]
WantedBy=default.target
""",
        "aipc-panel-mirror.service": f"""[Unit]
Description=Mirror Dock/top-bar structure across screens

[Service]
Type=oneshot
ExecStart={aipc_path} config preset mirror-dock
ExecStart={aipc_path} config preset mirror-topbar
""",
    }


def install_panel_mirror_units(home: Path, runner: RunnerT = subprocess.run) -> None:
    """Install + enable the systemd --user path unit that triggers
    mirror_dock/mirror_topbar automatically on every panel-config change.
    Resolves the `aipc` binary's actual path via shutil.which at install
    time rather than hardcoding /usr/local/bin/aipc (the shipped-image path
    -- a pipx dev install lives at ~/.local/bin/aipc instead, and systemd
    user services don't inherit that onto PATH by default). Idempotent.

    Also disables and removes the two superseded per-key sync units
    (aipc-dock-launcher-sync.*, aipc-panel-widget-sync.*) if present --
    this mirror covers everything they did and more (whole panel, not one
    config key on an already-matching widget list), so running both would
    just mean redundant, possibly conflicting writes on every trigger.
    """
    aipc_path = shutil.which("aipc") or "aipc"
    unit_dir = home / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    for old_name in ("aipc-dock-launcher-sync", "aipc-panel-widget-sync"):
        runner(["systemctl", "--user", "disable", "--now", f"{old_name}.path"], check=False)
        (unit_dir / f"{old_name}.path").unlink(missing_ok=True)
        (unit_dir / f"{old_name}.service").unlink(missing_ok=True)

    for name, content in panel_mirror_unit_files(aipc_path).items():
        (unit_dir / name).write_text(content)
    runner(["systemctl", "--user", "daemon-reload"], check=False)
    runner(["systemctl", "--user", "enable", "--now", "aipc-panel-mirror.path"], check=False)
