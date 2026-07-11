from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from aipc_lib import ccs_sync as ccs_sync_mod
from aipc_lib import config_menu as config_menu_mod
from aipc_lib import desktop_presets as desktop_presets_mod
from aipc_lib import doctor as doctor_mod
from aipc_lib import gate_client as gate_client_mod
from aipc_lib import log_append as log_append_mod
from aipc_lib import mem0_local_mcp as mem0_local_mcp_mod
from aipc_lib import mem0_migrate as mem0_migrate_mod
from aipc_lib import model_presets as model_presets_mod
from aipc_lib import models as models_mod
from aipc_lib import opencode_sync as opencode_sync_mod
from aipc_lib import panel_mirror as panel_mirror_mod
from aipc_lib import rag as rag_mod
from aipc_lib import screen_client
from aipc_lib import secrets
from aipc_lib import status_dashboard as status_mod
from aipc_lib import storage_reclaim as storage_reclaim_mod
from aipc_lib import tools_menu as tools_menu_mod
from aipc_lib import portal as portal_mod
from aipc_lib import voice_ops as voice_ops_mod
from aipc_lib import voice_ux as voice_ux_mod
from aipc_lib.codexbar_usage import usage_cli
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
LEMONADE_BASE_URL = "http://127.0.0.1:8001"
LEMONADE_UNLOAD_PATH = "/api/v0/unload"
BACKEND_HTTP_ERRORS = (urllib.error.URLError, TimeoutError, OSError)


def _sudo(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["sudo", *args] if os.geteuid() != 0 else list(args)
    return subprocess.run(cmd, check=check)


def _lemonade_model_name(model_or_alias: str) -> str:
    for entry in models_mod.load_manifest(models_mod.DEFAULT_MANIFEST):
        if entry.alias == model_or_alias and entry.backend == "lemonade":
            return entry.model_id
    return model_or_alias


def _lemonade_post(base_url: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read()
    return json.loads(body) if body[:1] in b"[{" else {}


@main.group("lemonade")
def lemonade_cmd() -> None:
    """Lemonade backend controls."""


def _lemonade_unload(model_name: str, base_url: str = LEMONADE_BASE_URL) -> bool:
    try:
        _lemonade_post(base_url, LEMONADE_UNLOAD_PATH, {"model_name": model_name})
        return True
    except BACKEND_HTTP_ERRORS as e:
        click.echo(f"lemonade unload failed for {model_name}: {e}", err=True)
        click.echo("If it is stuck in-flight, use: sudo systemctl restart lemonade.service", err=True)
        return False


@lemonade_cmd.command("unload")
@click.argument("model", default="coder-agentic", required=False)
@click.option("--base-url", default=LEMONADE_BASE_URL, show_default=True)
def lemonade_unload(model: str, base_url: str) -> None:
    """Unload a Lemonade model by aipc alias or raw Lemonade model id."""
    model_name = _lemonade_model_name(model)
    if not _lemonade_unload(model_name, base_url):
        sys.exit(1)
    click.echo(f"lemonade unload requested: {model} -> {model_name}")


@main.group("storage")
def storage_cmd() -> None:
    """Storage maintenance helpers."""


@storage_cmd.command("reclaim-live")
@click.option("--confirm", is_flag=True, help="Actually delete AIPC_LIVE after typing the confirmation phrase.")
def storage_reclaim_live(confirm: bool) -> None:
    """Reclaim the adjacent AIPC_LIVE install partition into the running rootfs."""
    sys.exit(storage_reclaim_mod.run_reclaim(confirm))


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


@main.group("agent")
def agent_cmd() -> None:
    """Agent runtime controls (phase-4-agent)."""


@agent_cmd.group("gate")
def agent_gate_cmd() -> None:
    """Grant/revoke/inspect risky-action permissions via aipc-agent-gate (D5).

    Thin client over the UNIX socket at /run/aipc-agent-gate.sock --
    see modules/agent-gate/README.md for the wire protocol.
    """


@agent_gate_cmd.command("grant")
@click.option("--scope", type=click.Choice(["session", "task"]), required=True)
@click.option("--actions", required=True, help="Comma-separated action names, e.g. screen-control,git-push")
@click.argument("duration_or_task_id")
def agent_gate_grant(scope: str, actions: str, duration_or_task_id: str) -> None:
    """Grant ACTIONS. DURATION_OR_TASK_ID is seconds for --scope session,
    or a task id string for --scope task."""
    actions_list = [a.strip() for a in actions.split(",") if a.strip()]
    req: dict = {"cmd": "grant", "actions": actions_list, "scope": scope}
    if scope == "session":
        try:
            req["duration_seconds"] = int(duration_or_task_id)
        except ValueError:
            click.echo("session scope needs an integer duration in seconds", err=True)
            sys.exit(1)
    else:
        req["task_id"] = duration_or_task_id
    resp = gate_client_mod.send(req)
    click.echo(json.dumps(resp))
    if "error" in resp:
        sys.exit(1)


@agent_gate_cmd.command("revoke")
@click.option("--grant-id", default=None)
@click.option("--task-id", default=None)
def agent_gate_revoke(grant_id: str | None, task_id: str | None) -> None:
    """Revoke a single grant (--grant-id) or every task-scoped grant for --task-id."""
    if not grant_id and not task_id:
        click.echo("revoke needs --grant-id or --task-id", err=True)
        sys.exit(1)
    req: dict = {"cmd": "revoke"}
    if grant_id:
        req["grant_id"] = grant_id
    if task_id:
        req["task_id"] = task_id
    resp = gate_client_mod.send(req)
    click.echo(json.dumps(resp))
    if "error" in resp:
        sys.exit(1)


@agent_gate_cmd.command("status")
def agent_gate_status() -> None:
    """List active (non-expired) grants."""
    resp = gate_client_mod.send({"cmd": "status"})
    if "error" in resp:
        click.echo(json.dumps(resp), err=True)
        sys.exit(1)

    table = Table(title="aipc agent gate status")
    for col in ("grant_id", "actions", "scope", "expires_at", "task_id", "granted_at"):
        table.add_column(col)
    for g in resp.get("grants", []):
        table.add_row(
            g.get("grant_id", ""),
            ",".join(g.get("actions", [])),
            g.get("scope", ""),
            str(g.get("expires_at")),
            str(g.get("task_id")),
            str(g.get("granted_at")),
        )
    Console().print(table)


@agent_cmd.group("oauth")
def agent_oauth_cmd() -> None:
    """Provision OAuth-backed tool credentials (phase-4-agent#4.2)."""


@agent_oauth_cmd.command("google")
@click.option(
    "--client-secret",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the Google OAuth client_secret.json (downloaded from Google Cloud Console).",
)
@click.option(
    "--token-path",
    default="/var/lib/aipc-agent/oauth/google.json",
    show_default=True,
    help="Where to store the resulting token (0600, user-owned, never baked).",
)
def agent_oauth_google(client_secret: str, token_path: str) -> None:
    """Run the interactive Google Calendar OAuth consent flow.

    Opens a local browser for consent, then stores the refresh token at
    --token-path. See modules/agent-tools-calendar/README.md.
    """
    sys.path.insert(0, "/usr/lib/aipc-agent")
    try:
        from aipc_agent_tools_calendar import run_google_oauth_flow
    except ImportError:
        click.echo(
            "aipc_agent_tools_calendar not installed — is the "
            "agent-tools-calendar module rendered on this image?",
            err=True,
        )
        sys.exit(1)
    result = run_google_oauth_flow(client_secret, token_path=token_path)
    click.echo(json.dumps(result))
    if result.get("status") != "ok":
        sys.exit(1)


@agent_cmd.command("screen")
@click.option("--mode", type=click.Choice(["session", "always"]), default=None)
@click.option("--revoke", is_flag=True, default=False)
@click.argument("duration", required=False)
def agent_screen_cmd(mode: str | None, revoke: bool, duration: str | None) -> None:
    """Grant/revoke screen-control permission (phase-4-agent#5.3).

    `aipc agent screen --mode session <seconds>` | `--mode always` | `--revoke`.
    A grant only lifts the gate check -- it never bypasses the window-class
    blacklist at /etc/aipc/agent-gate/screen-blacklist.conf.
    """
    if revoke:
        resp = screen_client.revoke()
    elif mode == "session":
        if not duration:
            click.echo("--mode session needs a DURATION in seconds", err=True)
            sys.exit(1)
        resp = screen_client.grant_session(duration)
    elif mode == "always":
        resp = screen_client.grant_always()
    else:
        click.echo("need --mode session <duration>, --mode always, or --revoke", err=True)
        sys.exit(1)
    click.echo(json.dumps(resp))
    if "error" in resp:
        sys.exit(1)


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

    backend = doctor_mod.check_active_backend()
    if backend is not None:
        results.append(backend)

    vectors = doctor_mod.check_vector_count()
    if vectors is not None:
        results.append(vectors)

    results.extend(doctor_mod.check_voice_once())

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
main.add_command(usage_cli, name="usage")


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


def _resolve_entry(alias: str, manifest: Path) -> models_mod.ModelEntry | None:
    for entry in models_mod.load_manifest(manifest):
        if entry.alias == alias:
            return entry
    return None


@models_cmd.command("loaded")
@click.option(
    "--manifest",
    type=click.Path(path_type=Path),
    default=models_mod.DEFAULT_MANIFEST,
    show_default=True,
)
def models_loaded(manifest: Path) -> None:
    """Show models actually loaded in memory by Ollama and/or Lemonade.

    Cloud aliases never appear here — they live in remote providers,
    not on this machine's GPU/NPU RAM.
    """
    console = Console()
    entries_by_backend: dict[str, list[models_mod.ModelEntry]] = {}
    for e in models_mod.load_manifest(manifest):
        if not e.is_cloud:
            entries_by_backend.setdefault(e.backend, []).append(e)

    has_anything = False
    for backend in ("lemonade", "ollama"):
        if backend not in entries_by_backend:
            continue
        has_anything = True
        if backend == "ollama":
            loaded = status_mod.loaded_models()
            title = f"Ollama — currently loaded models ({status_mod.DEFAULT_OLLAMA_BASE})"
        else:
            loaded = status_mod.loaded_lemonade_models()
            title = f"Lemonade — currently loaded models ({status_mod.DEFAULT_LEMONADE_BASE})"

        table = Table(title=title)
        table.add_column("alias")
        table.add_column("model_id")
        table.add_column("backend")
        table.add_column("detail")

        if loaded is None:
            click.echo(f"{backend}: not reachable at " +
                       (status_mod.DEFAULT_OLLAMA_BASE if backend == "ollama" else status_mod.DEFAULT_LEMONADE_BASE))
            continue

        if not loaded:
            click.echo(f"{backend}: no models currently loaded.")
            continue

        loaded_ids = {m.get("model_name") if backend == "lemonade" else m.get("name"): m
                      for m in loaded}
        for entry in entries_by_backend[backend]:
            raw = loaded_ids.get(entry.model_id)
            if raw is None:
                continue
            detail_parts = []
            if backend == "ollama":
                size_gb = raw.get("size", 0) / 1e9
                detail_parts.append(f"{size_gb:.1f}GB")
                expires = raw.get("expires_at")
                if expires and expires != 0:
                    detail_parts.append(f"expires {expires}")
            else:
                if raw.get("pinned"):
                    detail_parts.append("pinned")
                if raw.get("vram_loaded"):
                    detail_parts.append("vram_loaded")
            table.add_row(
                entry.alias,
                entry.model_id,
                backend,
                " | ".join(detail_parts) or "-",
            )
        if table.row_count:
            console.print(table)
        else:
            click.echo(f"{backend}: none of the declared models are in memory.")

    if not has_anything:
        click.echo("No local-backend models declared in " + str(manifest))


def _ollama_unload(model_name: str) -> bool:
    # Ollama's unload mechanism: keep_alive=0 forces immediate unloading.
    data = json.dumps({"model": model_name, "keep_alive": 0}).encode()
    req = urllib.request.Request(
        status_mod.DEFAULT_OLLAMA_BASE + "/api/generate",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except BACKEND_HTTP_ERRORS as e:
        click.echo(f"ollama unload failed for {model_name}: {e}", err=True)
        return False


@models_cmd.command("unload")
@click.argument("alias")
@click.option(
    "--manifest",
    type=click.Path(path_type=Path),
    default=models_mod.DEFAULT_MANIFEST,
    show_default=True,
)
def models_unload(alias: str, manifest: Path) -> None:
    """Unload a model by aipc alias, regardless of backend.

    Looks up the alias in models.yaml to find the backend and raw model_id,
    then dispatches to the appropriate unload API (Ollama keep_alive=0 or
    Lemonade POST /api/v0/unload).
    """
    entry = _resolve_entry(alias, manifest)
    if entry is None:
        click.echo(f"unknown alias: {alias!r} (not in {manifest})", err=True)
        sys.exit(1)
    if entry.is_cloud:
        click.echo(f"{alias} is a cloud model — nothing to unload locally.", err=True)
        sys.exit(1)

    if entry.backend == "ollama":
        ok = _ollama_unload(entry.model_id)
        if ok:
            click.echo(f"ollama unload requested: {alias} -> {entry.model_id}")
        else:
            sys.exit(1)
    elif entry.backend == "lemonade":
        if not _lemonade_unload(entry.model_id):
            sys.exit(1)
        click.echo(f"lemonade unload requested: {alias} -> {entry.model_id}")
    else:
        click.echo(f"unsupported backend for unload: {entry.backend}", err=True)
        sys.exit(1)


def _ollama_warm(model_name: str, keep_alive: str = "15m") -> bool:
    """Issue a tiny generate so Ollama loads the model and applies keep_alive."""
    data = json.dumps(
        {
            "model": model_name,
            "prompt": "ok",
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"num_predict": 1},
        }
    ).encode()
    req = urllib.request.Request(
        status_mod.DEFAULT_OLLAMA_BASE + "/api/generate",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        # Cold 122B load can take minutes.
        with urllib.request.urlopen(req, timeout=900) as resp:
            resp.read()
        return True
    except BACKEND_HTTP_ERRORS as e:
        click.echo(f"ollama warm failed for {model_name}: {e}", err=True)
        return False


def _lemonade_warm(model_name: str) -> bool:
    """Tiny chat completion so Lemonade auto-loads the model on first use."""
    data = json.dumps(
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()
    req = urllib.request.Request(
        LEMONADE_BASE_URL.rstrip("/") + "/v1/chat/completions",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp.read()
        return True
    except BACKEND_HTTP_ERRORS as e:
        click.echo(f"lemonade warm failed for {model_name}: {e}", err=True)
        return False


@models_cmd.command("use")
@click.argument(
    "preset",
    required=False,
    type=click.Choice(sorted(model_presets_mod.PRESETS.keys())),
)
@click.option(
    "--manifest",
    type=click.Path(path_type=Path),
    default=models_mod.DEFAULT_MANIFEST,
    show_default=True,
)
@click.option(
    "--list",
    "list_presets",
    is_flag=True,
    help="List presets and exit.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print unload/warm plan only; do not call backends.",
)
@click.option(
    "--no-warm",
    is_flag=True,
    help="Skip warm-load after unload (faster; first request pays load cost).",
)
def models_use(
    preset: str | None,
    manifest: Path,
    list_presets: bool,
    dry_run: bool,
    no_warm: bool,
) -> None:
    """Switch mutually exclusive local-model presets (agent vs 122B vs voice).

    122B (~81GB) and Lemonade Vulkan agent models must not co-reside on
    128GB UMA. `voice` (and `free`) unload those heavies so Cosy ROCm TTS
    and the NPU closed loop are not thrashing with agent weights. Never
    stops STT/TTS/mem0 services.
    """
    if list_presets or preset is None:
        for name, desc in sorted(model_presets_mod.PRESETS.items()):
            click.echo(f"{name}: {desc}")
        if preset is None and not list_presets:
            click.echo(
                "Usage: aipc models use <agent|122b|free|voice>", err=True
            )
            sys.exit(0 if list_presets else 1)
        if list_presets:
            return

    entries = models_mod.load_manifest(manifest)
    loaded_ollama = status_mod.loaded_models()
    loaded_lemonade = status_mod.loaded_lemonade_models()

    # None = backend unreachable (or dry-run wants full candidate list):
    # plan unloads for all matching declared aliases and attempt them.
    # empty set = reachable and nothing loaded: skip unloads.
    if dry_run:
        ollama_ids = None
        lemonade_ids = None
    else:
        ollama_ids = (
            None
            if loaded_ollama is None
            else {m.get("name", "") for m in loaded_ollama if m.get("name")}
        )
        lemonade_ids = (
            None
            if loaded_lemonade is None
            else {
                m.get("model_name", "")
                for m in loaded_lemonade
                if m.get("model_name")
            }
        )
        if loaded_ollama is None:
            click.echo("  warn: Ollama unreachable; will still try declared ollama unloads", err=True)
        if loaded_lemonade is None:
            click.echo(
                "  warn: Lemonade unreachable; will still try declared lemonade unloads",
                err=True,
            )

    try:
        plan = model_presets_mod.plan_switch(
            preset,
            entries,
            loaded_ollama_ids=ollama_ids,
            loaded_lemonade_ids=lemonade_ids,
        )
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    click.echo(f"preset: {plan.preset}")
    for note in plan.notes:
        click.echo(f"  note: {note}")

    if not plan.unloads:
        click.echo("  unload: (nothing currently loaded that this preset frees)")
    for u in plan.unloads:
        click.echo(f"  unload: {u.alias} ({u.backend}: {u.model_id})")
        if dry_run:
            continue
        if u.backend == "ollama":
            if not _ollama_unload(u.model_id):
                sys.exit(1)
        elif u.backend == "lemonade":
            if not _lemonade_unload(u.model_id):
                sys.exit(1)

    if plan.warm and not no_warm:
        click.echo(f"  warm: {plan.warm.alias} ({plan.warm.backend}: {plan.warm.model_id})")
        if not dry_run:
            if plan.warm.backend == "ollama":
                if not _ollama_warm(plan.warm.model_id):
                    sys.exit(1)
                click.echo(f"  warm ok: {plan.warm.alias}")
            elif plan.warm.backend == "lemonade":
                if not _lemonade_warm(plan.warm.model_id):
                    sys.exit(1)
                click.echo(f"  warm ok: {plan.warm.alias}")
    elif plan.warm and no_warm:
        click.echo(f"  warm skipped: {plan.warm.alias}")

    if not dry_run:
        click.echo("done.")


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
@click.option("--mem0-local", is_flag=True, help="Configure Claude Code's mem0 plugin to use the local mem0 service.")
@click.option("--no-tui", is_flag=True, help="Plain sequential y/N prompts instead of the TUI.")
def config_tools(mem0_local: bool, no_tui: bool) -> None:
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
    if mem0_local:
        try:
            paths = mem0_local_mcp_mod.point_claude_plugin()
        except mem0_local_mcp_mod.Mem0LocalMcpError as e:
            click.echo(f"mem0-local failed: {e}", err=True)
            sys.exit(1)
        for path in paths:
            click.echo(f"configured {path} -> local mem0 service")
        click.echo(f"Done ({len(paths)} file(s)). Restart Claude Code for the mem0 MCP to reconnect locally.")
        return

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
            if installed and tool.uninstall_marks_absent:
                continue
            action = tool.uninstall if installed else tool.install
            verb = tool.uninstall_label if installed else tool.install_label
            if not click.confirm(f"  {verb} {tool.name}?", default=False):
                continue
            result = action()
            if result.returncode != 0:
                click.echo(f"  {tool.name}: {verb.lower()} failed (exit {result.returncode})", err=True)
            else:
                click.echo(f"  {tool.name}: {verb.lower()} done")


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
    """Apply a desktop preset by name (see `aipc config preset list`), and
    make sure the standing cross-screen panel-mirror service is installed --
    two different things (one-shot preset vs. background sync service),
    bundled here purely for convenience since most users want both."""
    try:
        desktop_presets_mod.apply_preset(name, Path.home())
    except KeyError:
        click.echo(f"Unknown preset: {name!r} (see `aipc config preset list`)", err=True)
        sys.exit(1)
    panel_mirror_mod.install_panel_mirror_units(Path.home())
    click.echo(f"Applied preset: {name}")


@config_preset.command("mirror-dock", hidden=True)
def config_preset_mirror_dock() -> None:
    """Internal: mirror the Dock's entire structure (widget list, order,
    every widget's own config) across screens -- whichever screen changed
    propagates to the others. Meant to be triggered by a systemd --user
    path unit watching plasma-org.kde.plasma.desktop-appletsrc, not run by
    hand. Supersedes the narrower reconcile_dock_launchers (single config
    key on an already-matching widget list)."""
    panel_mirror_mod.mirror_dock()


@config_preset.command("mirror-topbar", hidden=True)
def config_preset_mirror_topbar() -> None:
    """Internal: same as mirror-dock, for the top bar. Not run by hand."""
    panel_mirror_mod.mirror_topbar()


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


@main.group("rag")
def rag_cmd() -> None:
    """Inspect and manage memory-rag's ingest watchers (openspec/changes/phase-2-memory#7)."""


@rag_cmd.command("list-sources")
def rag_list_sources() -> None:
    """Print the canonical source list with default-enabled state."""
    table = Table(title="aipc rag sources")
    table.add_column("source")
    table.add_column("service")
    table.add_column("default")
    for s in rag_mod.SOURCES:
        table.add_row(s.name, s.service, "enabled" if s.default_enabled else "disabled (consent)")
    Console().print(table)


@rag_cmd.command("status")
def rag_status() -> None:
    """Per-source last-cycle timestamp + vector count + service state."""
    table = Table(title="aipc rag status")
    table.add_column("source")
    table.add_column("active")
    table.add_column("vector_count")
    table.add_column("last_cycle")
    for s in rag_mod.SOURCES:
        st = rag_mod.source_status(s)
        color = "green" if st["active"] else "yellow"
        table.add_row(
            st["source"],
            f"[{color}]{st['active']}[/{color}]",
            str(st["vector_count"]),
            str(st["last_cycle"] or "-"),
        )
    Console().print(table)


@rag_cmd.command("enable")
@click.argument("source")
def rag_enable(source: str) -> None:
    """Enable a source's watcher and record consent where applicable."""
    try:
        s = rag_mod.find_source(source)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    rag_mod.enable_source(s)
    click.echo(f"enabled: {s.name}")


@rag_cmd.command("disable")
@click.argument("source")
def rag_disable(source: str) -> None:
    """Disable a source's watcher and withdraw consent where applicable."""
    try:
        s = rag_mod.find_source(source)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    rag_mod.disable_source(s)
    click.echo(f"disabled: {s.name}")


@rag_cmd.command("reindex")
@click.argument("source")
def rag_reindex(source: str) -> None:
    """Drop a source's vectors + state cache, then restart its watcher from scratch."""
    try:
        s = rag_mod.find_source(source)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    rag_mod.reindex_source(s)
    click.echo(f"reindexing: {s.name}")


@rag_cmd.command("purge")
@click.argument("source")
@click.option("--confirm", is_flag=True, help="Required — this is irreversible.")
def rag_purge(source: str, confirm: bool) -> None:
    """Drop a source's vectors + state cache. Does not touch the service/consent."""
    try:
        s = rag_mod.find_source(source)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if not confirm:
        click.echo("Refusing to purge without --confirm (irreversible).", err=True)
        sys.exit(1)
    n = rag_mod.purge_source(s)
    click.echo(f"purged {n} vectors for {s.name}")


@main.group("mem0")
def mem0_cmd() -> None:
    """mem0 SaaS -> local host migration (openspec/changes/phase-2-memory)."""


@mem0_cmd.command("migrate-from-saas")
@click.option(
    "--key-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a file containing the Mem0 SaaS API key. Falls back to $MEM0_API_KEY.",
)
@click.option("--apply", is_flag=True, help="Write to the local mem0 host. Default is dry-run.")
def mem0_migrate_from_saas(key_file: Path | None, apply: bool) -> None:
    """Pull all SaaS memories (every user/agent/app/run scope) and import them locally."""
    try:
        api_key = mem0_migrate_mod.read_api_key(key_file)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    result = mem0_migrate_mod.migrate_from_saas(api_key, apply=apply)
    if not apply:
        click.echo(f"dry-run: {result.fetched} SaaS memories found, 0 imported (pass --apply to write)")
        return
    click.echo(f"imported {result.imported}/{result.fetched} memories into local mem0")


@main.group("voice")
def voice_cmd() -> None:
    """Local voice assistant baseline (SenseVoice + Kokoro + helpers).

    Install/enable path is still the modules/ tree (bootc or ansible render).
    This group is the day-to-day control plane so operators do not hand-start
    units or containers outside aipc.
    """


@voice_cmd.command("status")
def voice_status() -> None:
    """Show closed-loop health: STT → LLM → TTS → mem0 → portal."""
    probes = voice_ops_mod.collect_baseline_status()
    click.echo(voice_ops_mod.format_status(probes))
    required = ("sensevoice", "resident-small", "litellm", "chat", "kokoro", "mem0")
    bad = [p for p in probes if not p.ok and p.name in required]
    if bad:
        sys.exit(1)


@voice_cmd.command("loop")
def voice_loop() -> None:
    """Alias for status — closed-loop probe (hear→think→speak→remember→UI)."""
    voice_status()


@voice_cmd.command("start")
@click.option("--dry-run", is_flag=True, help="Print commands only.")
def voice_start(dry_run: bool) -> None:
    """Start baseline STT/TTS/mem0 (tolerates missing optional units)."""
    results = voice_ops_mod.apply_plan(voice_ops_mod.plan_start(), dry_run=dry_run)
    for argv, code, msg in results:
        line = " ".join(argv)
        if dry_run:
            click.echo(f"dry-run: {line}")
            continue
        # Missing unit/container is expected on partial installs.
        if code == 0:
            click.echo(f"ok: {line}")
        else:
            click.echo(f"skip/fail ({code}): {line}" + (f" — {msg}" if msg else ""), err=True)
    if not dry_run:
        voice_status()


@voice_cmd.command("stop")
@click.option("--dry-run", is_flag=True, help="Print commands only.")
@click.option(
    "--yes",
    is_flag=True,
    help="Required: stop is for maintenance; baseline is meant to stay up.",
)
def voice_stop(dry_run: bool, yes: bool) -> None:
    """Stop SenseVoice + Kokoro only (mem0 and resident-small stay)."""
    if not dry_run and not yes:
        click.echo("Refusing to stop without --yes (baseline is always-on).", err=True)
        sys.exit(1)
    results = voice_ops_mod.apply_plan(voice_ops_mod.plan_stop(), dry_run=dry_run)
    for argv, code, msg in results:
        line = " ".join(argv)
        if dry_run:
            click.echo(f"dry-run: {line}")
            continue
        if code == 0:
            click.echo(f"ok: {line}")
        else:
            click.echo(f"skip/fail ({code}): {line}" + (f" — {msg}" if msg else ""), err=True)


@voice_cmd.command("once")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def voice_once(args: tuple[str, ...]) -> None:
    """Run one push-to-talk turn (forwards to aipc-voice-once)."""
    helper = voice_ops_mod.resolve_helper("once")
    if helper is None:
        click.echo(
            "aipc-voice-once not found; install/enable modules/voice-pipecat "
            "(bootc/ansible) or copy the helper into PATH.",
            err=True,
        )
        sys.exit(1)
    raise SystemExit(subprocess.call([str(helper), *args]))


@voice_cmd.command("timings")
@click.option("--last", type=int, default=20, help="show only the most recent N turns")
@click.option("--json", "as_json", is_flag=True, help="raw JSON output")
def voice_timings(last: int, as_json: bool) -> None:
    """Show recent voice turn latency (perceived / llm_ttft / tts_ttfa)."""
    from aipc_lib import voice_timing

    records = voice_timing.read_records(last=last)
    click.echo(voice_timing.format_report(records, as_json=as_json))


@voice_cmd.command("bind-hotkey")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def voice_bind_hotkey(args: tuple[str, ...]) -> None:
    """Bind desktop push-to-talk (forwards to aipc-voice-bind-hotkey)."""
    helper = voice_ops_mod.resolve_helper("bind-hotkey")
    if helper is None:
        click.echo("aipc-voice-bind-hotkey not found; enable voice-pipecat.", err=True)
        sys.exit(1)
    raise SystemExit(subprocess.call([str(helper), *args]))


@voice_cmd.command("krunner-install")
def voice_krunner_install() -> None:
    """Install KRunner (KDE global search) plugin for Spotlight-style AIPC."""
    candidates = [
        Path.home() / ".local/bin/aipc-krunner-install",
        Path("/usr/bin/aipc-krunner-install"),
        Path("/usr/local/bin/aipc-krunner-install"),
        REPO_ROOT
        / "modules/voice-pipecat/files/usr/bin/aipc-krunner-install",
    ]
    helper = next((p for p in candidates if p.is_file()), None)
    if helper is None:
        click.echo("aipc-krunner-install not found", err=True)
        sys.exit(1)
    raise SystemExit(subprocess.call([sys.executable, str(helper)]))


@voice_cmd.command("record-clone")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def voice_record_clone(args: tuple[str, ...]) -> None:
    """Record/refresh CosyVoice clone.wav (forwards to aipc-voice-record-clone)."""
    helper = voice_ops_mod.resolve_helper("record-clone")
    if helper is None:
        click.echo("aipc-voice-record-clone not found; enable voice-pipecat.", err=True)
        sys.exit(1)
    raise SystemExit(subprocess.call([str(helper), *args]))


@voice_cmd.group("ux", invoke_without_command=True)
@click.pass_context
def voice_ux_cmd(ctx: click.Context) -> None:
    """Shared voice UX (status file + overlay + notify).

    Schema: $XDG_RUNTIME_DIR/aipc-voice-state.json — same contract used by
    voice-wake, voice-once, aipc-voice-overlay, and other aipc callers.
    """
    if ctx.invoked_subcommand is not None:
        return
    click.echo(voice_ux_mod.format_ux_line())
    for name, detail, ok in voice_ux_mod.collect_ux_probes():
        mark = "ok" if ok else "!!"
        click.echo(f"{mark}  {name:<10}  {detail}")


@voice_ux_cmd.command("set")
@click.argument("state")
@click.argument("detail", required=False, default="")
@click.option("--no-notify", is_flag=True, help="Write status only (no desktop notify).")
@click.option("--no-cue", is_flag=True, help="Skip short espeak cue.")
def voice_ux_set(state: str, detail: str, no_notify: bool, no_cue: bool) -> None:
    """Publish a UX state for overlay/notify (any aipc-integrated surface)."""
    if state not in voice_ux_mod.KNOWN_STATES:
        click.echo(
            f"unknown state {state!r}; known: {', '.join(sorted(voice_ux_mod.KNOWN_STATES))}",
            err=True,
        )
        sys.exit(2)
    st = voice_ux_mod.announce(
        state,
        detail,
        notify=False if no_notify else None,  # None = auto (anti-spam)
        cue=not no_cue,
        force=True,
    )
    click.echo(voice_ux_mod.format_ux_line(st))


@voice_ux_cmd.command("get")
def voice_ux_get() -> None:
    """Print current shared UX status JSON path + fields."""
    st = voice_ux_mod.read_status()
    click.echo(voice_ux_mod.format_ux_line(st))


@voice_cmd.command("ptt")
def voice_ptt() -> None:
    """Push-to-talk via wake single-mic path (same as 控制中心)."""
    ok, msg = voice_ux_mod.request_ptt()
    if not ok:
        click.echo(msg, err=True)
        sys.exit(1)
    voice_ux_mod.announce("wake", "aipc voice ptt", force=True)
    voice_ux_mod.announce("recording", force=True)
    click.echo(f"ptt → {msg}")


@voice_cmd.group("overlay", invoke_without_command=True)
@click.pass_context
def voice_overlay_cmd(ctx: click.Context) -> None:
    """Siri-like partial overlay (user session unit aipc-voice-overlay)."""
    if ctx.invoked_subcommand is not None:
        return
    code, msg = voice_ux_mod.overlay_control("status")
    click.echo(f"aipc-voice-overlay: {msg}")
    if code != 0:
        sys.exit(code)


@voice_overlay_cmd.command("start")
def voice_overlay_start() -> None:
    """Enable+start the user overlay service."""
    subprocess.call(["systemctl", "--user", "enable", "aipc-voice-overlay.service"])
    code, msg = voice_ux_mod.overlay_control("restart")
    click.echo(msg or "started")
    raise SystemExit(code)


@voice_overlay_cmd.command("stop")
def voice_overlay_stop() -> None:
    code, msg = voice_ux_mod.overlay_control("stop")
    click.echo(msg or "stopped")
    raise SystemExit(code)


@voice_overlay_cmd.command("status")
def voice_overlay_status() -> None:
    code, msg = voice_ux_mod.overlay_control("status")
    click.echo(f"aipc-voice-overlay: {msg}")
    raise SystemExit(code)


@voice_overlay_cmd.command("ping")
def voice_overlay_ping() -> None:
    """Ping overlay widget control socket (API for other AIPC HUDs)."""
    ok, resp = voice_ux_mod.overlay_api_ping()
    click.echo(json.dumps(resp, ensure_ascii=False))
    raise SystemExit(0 if ok else 1)


@voice_overlay_cmd.command("api")
@click.argument("cmd")
@click.argument("args", nargs=-1)
@click.option("--source", default="cli", help="Widget / caller id")
@click.option("--priority", default=50, type=int, help="Preempt lower-priority holders")
@click.option("--detail", default="", help="Detail text for set")
def voice_overlay_api(cmd: str, args: tuple[str, ...], source: str, priority: int, detail: str) -> None:
    """Call overlay control API (show/hide/raise/set/get/clear/ping).

    Examples:
      aipc voice overlay api ping
      aipc voice overlay api set thinking --detail "agent working" --source hermes
      aipc voice overlay api hide
    """
    from aipc_lib import overlay_api

    fields: dict = {}
    c = cmd.lower()
    if c == "set":
        state = args[0] if args else "thinking"
        fields = {
            "state": state,
            "detail": detail or (" ".join(args[1:]) if len(args) > 1 else ""),
            "source": source,
            "priority": priority,
        }
    elif c == "clear":
        fields = {"source": source}
        if args:
            fields["source"] = args[0]
    try:
        resp = overlay_api.rpc(c, **fields)
    except OSError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    click.echo(json.dumps(resp, ensure_ascii=False))
    raise SystemExit(0 if resp.get("ok") else 1)


@main.group("portal", invoke_without_command=True)
@click.pass_context
def portal_cmd(ctx: click.Context) -> None:
    """Localhost AIPC manage portal (closed-loop status + actions).

    Prefer the installed aipc-portal.service when present; use
    `aipc portal serve` on live hosts before the next bootc switch.
    """
    if ctx.invoked_subcommand is not None:
        return
    url = portal_mod.portal_url()
    state = portal_mod.portal_status(url)
    probes = portal_mod.collect_status()
    click.echo(portal_mod.format_status_lines(probes, url=url, server_state=state))
    if state != "running":
        click.echo(
            "hint: portal server not running — try: aipc portal serve",
            err=True,
        )


@portal_cmd.command("open")
@click.option(
    "--no-start",
    is_flag=True,
    help="Do not auto-start the portal server if it is down.",
)
def portal_open(no_start: bool) -> None:
    """Open the portal in the default browser (auto-starts serve if needed)."""
    url = portal_mod.portal_url()
    if no_start:
        if portal_mod.portal_status(url) != "running":
            click.echo(
                f"portal not reachable at {url}; start with: aipc portal serve",
                err=True,
            )
            sys.exit(1)
        portal_mod.open_portal(url)
        click.echo(url + "/")
        return
    ok, message = portal_mod.ensure_and_open_portal(url)
    click.echo(message)
    if not ok:
        sys.exit(1)


@portal_cmd.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=7080, show_default=True, type=int)
def portal_serve(host: str, port: int) -> None:
    """Run the portal HTTP server in the foreground (live-host fallback)."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        click.echo("refusing non-localhost bind (portal is local-only)", err=True)
        sys.exit(2)
    roots = portal_mod.resolve_services_roots()
    click.echo(f"serving AIPC portal on http://{host}:{port}/")
    if roots:
        click.echo("metadata roots:")
        for r in roots:
            click.echo(f"  {r}")
    try:
        portal_mod.serve(host=host, port=port, roots=roots)
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    except OSError as exc:
        click.echo(f"bind failed: {exc}", err=True)
        sys.exit(1)


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
