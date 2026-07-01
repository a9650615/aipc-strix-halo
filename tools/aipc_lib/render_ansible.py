from __future__ import annotations

import yaml

from aipc_lib.modules import Module


def render(mods: list[Module]) -> str:
    tasks: list[dict] = []

    all_pkgs = [pkg for m in mods for pkg in m.packages]
    if all_pkgs:
        tasks.append({
            "name": "Install all packages",
            "dnf": {"name": all_pkgs, "state": "present"},
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

    play = [{"hosts": "aipc", "become": True, "tasks": tasks}]
    return yaml.dump(play, default_flow_style=False, sort_keys=False)
