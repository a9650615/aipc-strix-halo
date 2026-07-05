from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from aipc_lib import ccs_sync as ccs_sync_mod
from aipc_lib import config_menu as config_menu_mod
from aipc_lib import desktop_presets as desktop_presets_mod
from aipc_lib import doctor as doctor_mod
from aipc_lib import log_append as log_append_mod
from aipc_lib import models as models_mod
from aipc_lib import opencode_sync as opencode_sync_mod
from aipc_lib import secrets
from aipc_lib import status_dashboard as status_mod
from aipc_lib import tools_menu as tools_menu_mod
from aipc_lib.modules import discover
from aipc_lib.render_bootc import render as render_bootc
from aipc_lib.render_ansible import render as render_ansible

# ponytail: parents[2] assumes tools/aipc_lib/cli.py → repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = REPO_ROOT / "modules"

_DEFAULT_BOOTC_OUT = "targets/bootc/Containerfile.generated"
_DEFAULT_ANSIBLE_OUT = "targets/ansible/site.generated.yml"
_DEFAULT_BASE = "ghcr.io/ublue-os/bazzite-dx:stable"


@click.group()
def main() -> None:
    """aipc — render, doctor, and secrets for the AI PC image."""


# ponytail: power-guard enable/disable/status — 3 short systemctl/sentinel ops,
# not worth a sibling module. sudo-prefixed when run as a normal user.
POWER_GUARD_UNIT = "power-guard.service"
POWER_GUARD_SENTINEL = "/etc/aipc/power-guard.disabled"
POWER_GUARD_STATE = "/var/lib/aipc-power-guard/state.json"


def _sudo(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["sudo", *args] if os.geteuid() != 0 else list(args)
    return subprocess.run(cmd, check=check)


@main.group("power-guard")
def power_guard_cmd() -> None:
    """Battery back-feed guard: clamp CPU on weak AC + persist charge cap."""


@power_guard_cmd.command("enable")
def power_guard_enable() -> None:
    """Start the guard now and at boot (clears the kill-switch sentinel)."""
    _sudo(["rm", "-f", POWER_GUARD_SENTINEL], check=False)
    _sudo(["systemctl", "daemon-reload"], check=False)
    _sudo(["systemctl", "enable", "--now", POWER_GUARD_UNIT])
    click.echo("power-guard enabled — active now, autostarts at boot.")


@power_guard_cmd.command("disable")
def power_guard_disable() -> None:
    """Stop the guard and prevent autostart (sets the kill-switch sentinel)."""
    # --now sends SIGTERM → daemon's signal handler releases any clamp first.
    _sudo(["systemctl", "disable", "--now", POWER_GUARD_UNIT], check=False)
    _sudo(["touch", POWER_GUARD_SENTINEL], check=False)
    click.echo("power-guard disabled — kill switch set; any clamp released on stop.")


@power_guard_cmd.command("status")
def power_guard_status() -> None:
    """Show guard state, kill switch, and live sysfs values."""
    def _read(p: str) -> str:
        try:
            return Path(p).read_text().strip()
        except OSError:
            return "?"

    svc = subprocess.run(
        ["systemctl", "is-active", POWER_GUARD_UNIT],
        capture_output=True, text=True,
    ).stdout.strip() or "unknown"
    enabled = subprocess.run(
        ["systemctl", "is-enabled", POWER_GUARD_UNIT],
        capture_output=True, text=True,
    ).stdout.strip() or "unknown"
    sentinel = os.path.exists(POWER_GUARD_SENTINEL)
    state: dict = {}
    try:
        import json
        state = json.loads(Path(POWER_GUARD_STATE).read_text())
    except (OSError, ValueError):
        pass

    table = Table(title="aipc power-guard")
    table.add_column("key")
    table.add_column("value")
    table.add_row("service active", svc)
    table.add_row("autostart", enabled)
    table.add_row("kill switch", "SET (disabled)" if sentinel else "clear")
    table.add_row("daemon state", str(state.get("state", "?")))
    table.add_row("dry_run", str(state.get("dry_run", "?")))
    table.add_row("ac online", str(state.get("ac_online", _read("/sys/class/power_supply/AC0/online"))))
    table.add_row("bat status", str(state.get("bat_status", _read("/sys/class/power_supply/BAT0/status"))))
    table.add_row("power_now uW", str(state.get("power_now_uw", _read("/sys/class/power_supply/BAT0/power_now"))))
    table.add_row("cur freq factor", str(state.get("cur_factor", "?")))
    table.add_row("charge cap", _read("/sys/class/power_supply/BAT0/charge_control_end_threshold") + "%")
    Console().print(table)


@main.group()
def render() -> None:
    """Render build targets."""


@render.command("bootc")
@click.option("--base", default=_DEFAULT_BASE, show_default=True)
@click.option("--image-ref", required=True)
@click.option("--build-date", required=True)
@click.option("--out", default=_DEFAULT_BOOTC_OUT, show_default=True)
def render_bootc_cmd(base: str, image_ref: str, build_date: str, out: str) -> None:
    """Emit Containerfile for bootc image build."""
    mods = discover(MODULES_ROOT)
    content = render_bootc(mods, base=base, image_ref=image_ref, build_date=build_date)
    out_path = REPO_ROOT / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    click.echo(f"Written: {out_path}")


@render.command("ansible")
@click.option("--out", default=_DEFAULT_ANSIBLE_OUT, show_default=True)
def render_ansible_cmd(out: str) -> None:
    """Emit Ansible playbook."""
    mods = discover(MODULES_ROOT)
    content = render_ansible(mods)
    out_path = REPO_ROOT / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    click.echo(f"Written: {out_path}")


_STATUS_STYLE = {
    doctor_mod.STATUS_OK: "green",
    doctor_mod.STATUS_OPTIONAL: "cyan",
    doctor_mod.STATUS_WARN: "yellow",
    doctor_mod.STATUS_FAIL: "red",
}


@main.command()
def doctor() -> None:
    """Run verify.sh for every module and report status."""
    mods = discover(MODULES_ROOT)
    results = doctor_mod.run_all(mods)

    gw = doctor_mod.check_gateway_aliases()
    if gw is not None:
        results.append(gw)

    table = Table(title="aipc doctor")
    table.add_column("Module")
    table.add_column("Status")
    table.add_column("Message")

    all_ok = True
    for r in results:
        color = _STATUS_STYLE.get(r.status, "white")
        table.add_row(r.module, f"[{color}]{r.status}[/{color}]", r.message)
        if r.status == doctor_mod.STATUS_FAIL:
            all_ok = False

    Console().print(table)
    sys.exit(0 if all_ok else 1)


@main.group()
def secrets_cmd() -> None:
    """Manage SOPS-encrypted secrets."""


main.add_command(secrets_cmd, name="secrets")


@secrets_cmd.command("view")
@click.argument("path")
def secrets_view(path: str) -> None:
    """Decrypt and print a secrets file."""
    secrets.view(path)


@secrets_cmd.command("edit")
@click.argument("path")
def secrets_edit(path: str) -> None:
    """Open a secrets file in $EDITOR via sops."""
    secrets.edit(path)


@main.group("models")
def models_cmd() -> None:
    """Inspect and sync the model manifest."""


@models_cmd.command("list")
@click.option(
    "--manifest",
    type=click.Path(path_type=Path),
    default=models_mod.DEFAULT_MANIFEST,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path),
    default=models_mod.DEFAULT_MODELS_ROOT,
    show_default=True,
)
def models_list(manifest: Path, models_root: Path) -> None:
    """Print declared aliases, backend, size, and on-disk status."""
    entries = models_mod.load_manifest(manifest)
    if not entries:
        click.echo(f"No manifest at {manifest}")
        sys.exit(0)

    table = Table(title="aipc models")
    for col in ("alias", "backend", "model_id", "size_gb", "on_disk_status"):
        table.add_column(col)

    _STATUS_COLOR = {"present": "green", "missing": "red", "n/a": "dim"}
    for e in entries:
        status = models_mod.on_disk_status(e, models_root)
        color = _STATUS_COLOR.get(status, "white")
        table.add_row(
            e.alias,
            e.backend,
            e.model_id,
            str(e.size_gb) if e.size_gb is not None else "",
            f"[{color}]{status}[/{color}]",
        )
    Console().print(table)


@models_cmd.command("sync")
@click.option("--check", is_flag=True, help="Dry-run: exit non-zero if any declared model is missing.")
@click.option(
    "--manifest",
    type=click.Path(path_type=Path),
    default=models_mod.DEFAULT_MANIFEST,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path),
    default=models_mod.DEFAULT_MODELS_ROOT,
    show_default=True,
)
def models_sync(check: bool, manifest: Path, models_root: Path) -> None:
    """Sync model weights. --check is a dry-run; pulls nothing and just reports gaps."""
    entries = models_mod.load_manifest(manifest)
    if check:
        missing = models_mod.sync_check(entries, models_root)
        if missing:
            click.echo("Missing models:", err=True)
            for m in missing:
                click.echo(f"  - {m.alias} ({m.backend}: {m.model_id})", err=True)
            sys.exit(1)
        click.echo("All declared models present.")
        sys.exit(0)

    results = models_mod.sync_pull(entries, models_root)
    failed = [e for e, success in results if not success]
    for e, success in results:
        click.echo(f"{'pulled' if success else 'FAILED'}: {e.alias} ({e.backend}: {e.model_id})")
    if not results:
        click.echo("All declared models present.")
    sys.exit(1 if failed else 0)


@main.group()
def log() -> None:
    """Agent log operations."""


@log.command("append")
@click.option("--date", required=True)
@click.option("--role", required=True, type=click.Choice(log_append_mod.ROLES))
@click.option("--model", required=True)
@click.option("--run-label", required=True)
@click.option("--spec-task", "spec_tasks", required=True)
@click.option("--sha-range", "sha_range", required=True)
@click.option("--outcome", required=True)
def log_append_cmd(
    date: str, role: str, model: str, run_label: str, spec_tasks: str, sha_range: str, outcome: str
) -> None:
    """Append a row to docs/agent-log.md."""
    line = log_append_mod.append_row(date, role, model, run_label, spec_tasks, sha_range, outcome)
    click.echo(f"Appended: {line.rstrip()}")


@main.group()
def config() -> None:
    """Quick terminal-based settings adjustment (AI model tier, services)."""


@config.command("status")
def config_status() -> None:
    """Show installed dev-ai-* tool configs' current model tier and service health."""
    home = Path.home()
    table = Table(title="aipc config status")
    table.add_column("tool")
    table.add_column("config path")
    table.add_column("current tier")

    found = config_menu_mod.installed_configs(home)
    if not found:
        click.echo("No dev-ai-* tool configs found under " + str(home))
    for tc, path in found:
        tier = config_menu_mod.current_tier(path) or "?"
        table.add_row(tc.tool, str(path.relative_to(home)), tier)
    Console().print(table)

    svc_table = Table(title="AI services")
    svc_table.add_column("service")
    svc_table.add_column("status")
    for svc, status in config_menu_mod.service_status().items():
        color = "green" if status == "active" else "red"
        svc_table.add_row(svc, f"[{color}]{status}[/{color}]")
    Console().print(svc_table)


@config.command("model")
@click.option(
    "--tier",
    type=click.Choice(config_menu_mod.TIERS),
    help="Set directly without prompting (for scripting).",
)
def config_model(tier: str | None) -> None:
    """Switch the default model tier for aider/cline/goose.

    opencode is not included here — it's fixed to coder-agentic for
    reliable tool-calling (see modules/dev-ai-opencode/README.md). continue
    has no single default field; use its own /model picker.
    """
    home = Path.home()
    found = config_menu_mod.installed_configs(home)
    if not found:
        click.echo(f"No dev-ai-* tool configs found under {home}")
        sys.exit(1)

    if tier is None:
        click.echo("Tiers:")
        for i, t in enumerate(config_menu_mod.TIERS, start=1):
            click.echo(f"  {i}) {t}")
        choice = click.prompt("Pick a tier", type=click.IntRange(1, len(config_menu_mod.TIERS)))
        tier = config_menu_mod.TIERS[choice - 1]

    for tc, path in found:
        changed = config_menu_mod.set_tier(path, tier)
        status = f"-> {tier}" if changed else "(no tier field found, skipped)"
        click.echo(f"{tc.tool}: {status}")


@config.command("sync-opencode")
def config_sync_opencode() -> None:
    """Rewrite opencode's registered models from LiteLLM's live /v1/models.

    OpenCode has no dynamic model-discovery option of its own (confirmed
    against its docs) — this is that missing half, run by hand whenever
    the LiteLLM model_list changes instead of hand-editing opencode's
    config.json to match.
    """
    try:
        model_ids = opencode_sync_mod.sync_config()
    except (OSError, ValueError) as e:
        click.echo(f"sync failed: {e}", err=True)
        sys.exit(1)
    click.echo(f"Synced {len(model_ids)} models to {opencode_sync_mod.DEFAULT_OPENCODE_CONFIG}:")
    for mid in model_ids:
        click.echo(f"  - {mid}")


@config.command("sync-ccs")
def config_sync_ccs() -> None:
    """Rewrite ccs's ANTHROPIC_EXTRA_MODELS from LiteLLM's live /v1/models.

    Same problem as sync-opencode: CCS's aipc.settings.json is a static
    snapshot with no dynamic model-discovery of its own — this is that
    missing half, run by hand whenever the LiteLLM model_list changes.
    Requires `ccs api create` to have been run at least once already.
    """
    try:
        model_ids = ccs_sync_mod.sync_extra_models()
    except (OSError, ValueError) as e:
        click.echo(f"sync failed: {e}", err=True)
        sys.exit(1)
    click.echo(f"Synced {len(model_ids)} extra models to {ccs_sync_mod.DEFAULT_CCS_SETTINGS}:")
    for mid in model_ids:
        click.echo(f"  - {mid}")


@config.command("tools")
@click.option("--no-tui", is_flag=True, help="Plain sequential y/N prompts instead of the TUI.")
def config_tools(no_tui: bool) -> None:
    """Categorized checklist: which dev tools are installed, install more.

    This is the standalone, re-runnable half of ops-firstboot's aipc-init
    ai-tools screen (install only — see `aipc config model` for tier
    switching). Grouped into broad categories per user direction 2026-07-03
    ("大分類" over a flat list); add new categories here as new tool areas
    come online rather than growing any one category unboundedly.

    Default is a Textual TUI (keyboard Tab/Enter and mouse clicks both
    work, per user direction 2026-07-03 — "像 claude code"). --no-tui falls
    back to plain prompts for non-interactive/scripted use.
    """
    if not no_tui:
        from aipc_lib.tools_tui import run as run_tui

        run_tui()
        return

    for category, tools in tools_menu_mod.CATEGORIES.items():
        click.echo(f"\n=== {category} ===")
        for tool in tools:
            installed = tool.is_installed()
            status = "[installed]" if installed else "[not installed]"
            click.echo(f"  {tool.name} {status}")
            if installed:
                continue
            if not click.confirm(f"  Install {tool.name}?", default=False):
                continue
            result = tool.install()
            if result.returncode != 0:
                click.echo(f"  {tool.name}: install failed (exit {result.returncode})", err=True)
            else:
                click.echo(f"  {tool.name}: installed")


@config.group("preset")
def config_preset() -> None:
    """Desktop presets: bundled KDE Plasma tweaks (window buttons, touchpad, Dock, ...)."""


@config_preset.command("list")
def config_preset_list() -> None:
    """List available desktop presets."""
    for preset in desktop_presets_mod.list_presets():
        click.echo(f"{preset.name}: {preset.description}")


@config_preset.command("apply")
@click.argument("name")
def config_preset_apply(name: str) -> None:
    """Apply a desktop preset by name (see `aipc config preset list`)."""
    try:
        desktop_presets_mod.apply_preset(name, Path.home())
    except KeyError:
        click.echo(f"Unknown preset: {name!r} (see `aipc config preset list`)", err=True)
        sys.exit(1)
    click.echo(f"Applied preset: {name}")


@config_preset.command("sync-dock-launchers", hidden=True)
def config_preset_sync_dock_launchers() -> None:
    """Internal: reconcile Dock pinned-launcher lists across screens
    (whichever screen changed propagates to the others). Meant to be
    triggered by a systemd --user path unit watching
    plasma-org.kde.plasma.desktop-appletsrc, not run by hand."""
    desktop_presets_mod.reconcile_dock_launchers(
        Path.home() / desktop_presets_mod.DOCK_LAUNCHER_STATE_RELPATH
    )


@config_preset.command("sync-topbar-systemtray", hidden=True)
def config_preset_sync_topbar_systemtray() -> None:
    """Internal: reconcile top-bar systemtray icon visibility across screens.
    Same trigger and mechanism as sync-dock-launchers, not run by hand."""
    desktop_presets_mod.reconcile_topbar_systemtray(
        Path.home() / desktop_presets_mod.TOPBAR_SYSTEMTRAY_STATE_RELPATH
    )


@config_preset.command("rebuild-dock")
@click.argument("screen", type=int)
def config_preset_rebuild_dock(screen: int) -> None:
    """Rebuild one screen's Dock from scratch (fixes both stale display and
    wrong widget order at once -- see rebuild_dock_panel's docstring for why
    those need a full rebuild and what it costs). SCREEN is Plasma's
    panel.screen index (0, 1, ...), not a physical output name."""
    warning = desktop_presets_mod.rebuild_dock_panel(screen)
    if warning is None:
        click.echo(f"No Dock found on screen {screen}", err=True)
        sys.exit(1)
    click.echo(warning)


@main.command("status")
def status_cmd() -> None:
    """Dashboard: this repo's enabled module services + live loaded models."""
    console = Console()

    svc_table = Table(title="Module services (enabled modules only)")
    svc_table.add_column("module")
    svc_table.add_column("service")
    svc_table.add_column("status")

    pairs = status_mod.discover_module_services(MODULES_ROOT)
    if not pairs:
        click.echo(f"No module-shipped services found under {MODULES_ROOT}")
    for ms in pairs:
        state = status_mod.service_is_active(ms.service)
        color = "green" if state == "active" else ("red" if state == "failed" else "yellow")
        svc_table.add_row(ms.module, ms.service, f"[{color}]{state}[/{color}]")
    console.print(svc_table)

    models = status_mod.loaded_models()
    model_table = Table(title="Ollama — currently loaded models")
    model_table.add_column("model")
    model_table.add_column("size")
    model_table.add_column("expires_at")

    if models is None:
        click.echo("Ollama not reachable at " + status_mod.DEFAULT_OLLAMA_BASE)
    elif not models:
        click.echo("No models currently loaded.")
    else:
        for m in models:
            size_gb = m.get("size", 0) / 1e9
            name = status_mod.alias_display_name(m.get("name", "?"))
            model_table.add_row(name, f"{size_gb:.1f}GB", m.get("expires_at", "?"))
        console.print(model_table)


if __name__ == "__main__":
    main()
