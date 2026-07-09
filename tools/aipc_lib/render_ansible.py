from __future__ import annotations

import yaml

from aipc_lib.modules import Module


def _has_hwdb(mods: list[Module]) -> bool:
    for m in mods:
        hwdb_dir = m.path / "files/etc/udev/hwdb.d"
        if hwdb_dir.is_dir() and any(hwdb_dir.glob("*.hwdb")):
            return True
    return False


def render(mods: list[Module]) -> str:
    tasks: list[dict] = []

    all_pkgs = [pkg for m in mods for pkg in m.packages]
    if all_pkgs:
        tasks.append({
            "name": "Install all packages",
            "dnf": {"name": all_pkgs, "state": "present"},
        })

    # aipc CLI itself: not module-owned (tools/ lives at repo root), but every
    # image needs it for `aipc doctor`/`aipc render` post-switch — see the
    # matching comment in render_bootc.py. Target is /usr/bin, not
    # /usr/local/bin (that's a symlink to /var/usrlocal on this bootc image,
    # not writable at build time — see render_bootc.py's comment).
    tasks.append({
        "name": "Copy aipc CLI tooling",
        "copy": {"src": "tools/", "dest": "/usr/lib/aipc/tools/"},
    })
    tasks.append({
        "name": "Install aipc CLI",
        "shell": (
            "python3 -m venv /usr/lib/aipc/tools/.venv "
            "&& /usr/lib/aipc/tools/.venv/bin/pip install --no-cache-dir /usr/lib/aipc/tools "
            "&& ln -sf /usr/lib/aipc/tools/.venv/bin/aipc /usr/bin/aipc"
        ),
        "args": {"creates": "/usr/bin/aipc"},
    })

    for m in mods:
        if m.kargs:
            kargs_toml = ", ".join(f'"{k}"' for k in m.kargs)
            tasks.append({
                "name": f"{m.name}: install kargs file",
                "copy": {
                    "dest": f"/usr/lib/bootc/kargs.d/{m.name}.toml",
                    "mode": "0644",
                    "content": f'kargs = [{kargs_toml}]\n',
                },
            })

        files_dir = m.path / "files"
        if files_dir.is_dir():
            tasks.append({
                "name": f"Copy files for {m.name}",
                "copy": {"src": f"modules/{m.name}/files/", "dest": "/"},
            })

        modprobe_dir = m.path / "modprobe.d"
        if modprobe_dir.is_dir():
            tasks.append({
                "name": f"Copy modprobe.d for {m.name}",
                "copy": {"src": f"modules/{m.name}/modprobe.d/", "dest": "/etc/modprobe.d/"},
            })

        env_dir = m.path / "env"
        if env_dir.is_dir():
            tasks.append({
                "name": f"Copy env for {m.name}",
                "copy": {"src": f"modules/{m.name}/env/", "dest": f"/etc/aipc/env.d/{m.name}/"},
            })

        quadlet_dir = m.path / "quadlet"
        if quadlet_dir.is_dir():
            tasks.append({
                "name": f"Copy quadlet for {m.name}",
                "copy": {"src": f"modules/{m.name}/quadlet/", "dest": "/etc/containers/systemd/"},
            })

        post = m.path / "post-install.sh"
        if post.exists():
            tasks.append({
                "name": f"Run post-install for {m.name}",
                "script": f"modules/{m.name}/post-install.sh",
            })

    if _has_hwdb(mods):
        tasks.append({
            "name": "Update systemd hwdb",
            "shell": "systemd-hwdb update",
        })

    play = [{"hosts": "aipc", "become": True, "tasks": tasks}]
    return yaml.dump(play, default_flow_style=False, sort_keys=False)
