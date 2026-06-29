from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from aipc_lib import doctor as doctor_mod
from aipc_lib import log_append as log_append_mod
from aipc_lib import models as models_mod
from aipc_lib import secrets
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

    for e in entries:
        status = models_mod.on_disk_status(e, models_root)
        color = "green" if status == "present" else "red"
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
    """Sync model weights. --check is a dry-run; full sync is not yet implemented."""
    entries = models_mod.load_manifest(manifest)
    if check:
        missing = models_mod.sync_check(entries, models_root)
        if missing:
            click.echo("Missing models:", err=True)
            for m in missing:
                click.echo(f"  - {m.alias} ({m.backend}: {m.path})", err=True)
            sys.exit(1)
        click.echo("All declared models present.")
        sys.exit(0)

    # ponytail: full pull not yet wired — backends differ (Ollama pull vs Lemonade vs HF download)
    click.echo("aipc models sync (full pull) is not yet implemented. Use --check for a dry-run.")
    sys.exit(0)


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


if __name__ == "__main__":
    main()
