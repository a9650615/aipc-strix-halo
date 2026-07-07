from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_INSTALL_ROOTS = (Path("/etc/aipc/mem0"), Path("/usr/lib/aipc-mem0"))


class Mem0LocalMcpError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mem0Install:
    root: Path
    python: Path


def find_install(roots: Iterable[Path] = DEFAULT_INSTALL_ROOTS) -> Mem0Install:
    for root in roots:
        python = root / "venv/bin/python"
        if (root / "aipc_mem0").is_dir() and python.is_file() and os.access(python, os.X_OK):
            return Mem0Install(root=root, python=python)
    raise Mem0LocalMcpError(
        "aipc-mem0 module/venv not found under /etc/aipc/mem0 or /usr/lib/aipc-mem0; "
        "install/enable the memory-mem0 module first, then check with `aipc doctor`"
    )


def mcp_config(install: Mem0Install) -> dict:
    return {
        "mcpServers": {
            "mem0": {
                "_comment": (
                    "Claude plugin configured for the LOCAL aipc-mem0 service (offline; no SaaS quota). "
                    "Re-apply from aipc config tools after a plugin update."
                ),
                "type": "stdio",
                "command": str(install.python),
                "args": ["-m", "aipc_mem0.mcp_server"],
                "env": {
                    "PYTHONPATH": str(install.root),
                    "MEM0_TELEMETRY": "False",
                },
            }
        }
    }


def claude_plugin_paths(home: Path) -> list[Path]:
    return sorted((home / ".claude/plugins/cache/mem0-plugins/mem0").glob("*/.mcp.json"))


def _is_local_config(path: Path, install: Mem0Install) -> bool:
    try:
        mem0 = json.loads(path.read_text())["mcpServers"]["mem0"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False
    return (
        mem0.get("type") == "stdio"
        and mem0.get("command") == str(install.python)
        and mem0.get("args") == ["-m", "aipc_mem0.mcp_server"]
        and mem0.get("env", {}).get("PYTHONPATH") == str(install.root)
        and mem0.get("env", {}).get("MEM0_TELEMETRY") == "False"
    )


def claude_plugin_is_local(home: Path | None = None) -> bool:
    home = Path.home() if home is None else home
    try:
        install = find_install()
    except Mem0LocalMcpError:
        return False
    paths = claude_plugin_paths(home)
    return bool(paths) and all(_is_local_config(path, install) for path in paths)


def point_claude_plugin(home: Path | None = None, install: Mem0Install | None = None) -> list[Path]:
    home = Path.home() if home is None else home
    install = find_install() if install is None else install
    paths = claude_plugin_paths(home)
    if not paths:
        raise Mem0LocalMcpError(
            f"No mem0 plugin .mcp.json found under {home}/.claude/plugins/cache; "
            "install/enable the Claude Code mem0 plugin first"
        )

    data = json.dumps(mcp_config(install), indent=2) + "\n"
    for path in paths:
        path.write_text(data)
    return paths
