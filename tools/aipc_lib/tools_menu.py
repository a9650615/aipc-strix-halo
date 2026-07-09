from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aipc_lib import mem0_local_mcp

# Broad categories (per user direction 2026-07-03: "大分類" grouping over a
# flat list) — currently two; add more as new dev-tool areas come online
# (e.g. voice, gaming) rather than growing either list unboundedly.
#
# Scope boundary: this module only answers "is X installed / install it".
# Which model tier an installed tool points at is `aipc config model`'s job
# (modules/ops-firstboot's aipc-init does both at first-boot time; this is
# the standalone, re-runnable equivalent for the install half only).


@dataclass
class Tool:
    name: str
    is_installed: Callable[[], bool]
    install: Callable[[], subprocess.CompletedProcess]
    uninstall: Callable[[], subprocess.CompletedProcess]
    install_label: str = "Install"
    uninstall_label: str = "Remove"
    uninstall_marks_absent: bool = True


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False)


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _vscode_ext_installed(ext_id: str) -> bool:
    if not _has("code"):
        return False
    proc = subprocess.run(["code", "--list-extensions"], capture_output=True, text=True, check=False)
    return ext_id.lower() in proc.stdout.lower()


def _opencode_installed() -> bool:
    # distrobox auto-exports installed binaries to ~/.local/bin on the host.
    return _has("opencode")


def _remove_which(name: str) -> subprocess.CompletedProcess:
    """Best-effort removal of whatever binary `name` currently resolves to.

    Used for tools whose installer script picks its own drop location
    (goose, ccstatus) — if it's not on PATH there's nothing to remove.
    """
    path = shutil.which(name)
    if path:
        Path(path).unlink(missing_ok=True)
    return subprocess.CompletedProcess(args=["rm", path or name], returncode=0)


def _install_aider() -> subprocess.CompletedProcess:
    return _run(["pipx", "install", "aider-chat"])


def _uninstall_aider() -> subprocess.CompletedProcess:
    return _run(["pipx", "uninstall", "aider-chat"])


def _install_cline() -> subprocess.CompletedProcess:
    return _run(["code", "--install-extension", "saoudrizwan.claude-dev"])


def _uninstall_cline() -> subprocess.CompletedProcess:
    return _run(["code", "--uninstall-extension", "saoudrizwan.claude-dev"])


def _install_continue() -> subprocess.CompletedProcess:
    return _run(["code", "--install-extension", "Continue.continue", "--force"])


def _uninstall_continue() -> subprocess.CompletedProcess:
    return _run(["code", "--uninstall-extension", "Continue.continue"])


def _install_goose() -> subprocess.CompletedProcess:
    return subprocess.run(
        "curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | bash",
        shell=True,
        check=False,
    )


def _uninstall_goose() -> subprocess.CompletedProcess:
    return _remove_which("goose")


def _install_opencode() -> subprocess.CompletedProcess:
    has_node_box = subprocess.run(
        ["distrobox", "list"], capture_output=True, text=True, check=False
    )
    if "node" not in has_node_box.stdout:
        create = _run(["distrobox", "assemble", "create", "--file", "/etc/aipc/distrobox/node.ini"])
        if create.returncode != 0:
            return create
    return _run(["distrobox", "enter", "node", "--", "sudo", "npm", "install", "-g", "opencode-ai"])


def _uninstall_opencode() -> subprocess.CompletedProcess:
    return _run(["distrobox", "enter", "node", "--", "sudo", "npm", "uninstall", "-g", "opencode-ai"])


CCSTATUS_VERSION = "v0.3.0"
CCSTATUS_URL = (
    f"https://github.com/moonD4rk/ccstatus/releases/download/{CCSTATUS_VERSION}/"
    "ccstatus_linux_x86_64.tar.gz"
)


def _install_ccstatus() -> subprocess.CompletedProcess:
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        f"curl -fsSL {CCSTATUS_URL} | tar xz -C {bin_dir} ccstatus"
        f" && chmod +x {bin_dir}/ccstatus"
        f" && {bin_dir}/ccstatus init"
        f" && {bin_dir}/ccstatus install",
        shell=True,
        check=False,
    )
    return result


def _uninstall_ccstatus() -> subprocess.CompletedProcess:
    # Best-effort: undo the statusline registration before removing the
    # binary itself (ignore failure — it may already be gone/unregistered).
    subprocess.run(f"{Path.home() / '.local' / 'bin' / 'ccstatus'} uninstall", shell=True, check=False)
    return _remove_which("ccstatus")


def _mem0_local_service_configured() -> bool:
    return mem0_local_mcp.claude_plugin_is_local()


def _configure_mem0_local_service() -> subprocess.CompletedProcess:
    try:
        paths = mem0_local_mcp.point_claude_plugin()
    except mem0_local_mcp.Mem0LocalMcpError as e:
        return subprocess.CompletedProcess(args=["mem0-local"], returncode=1, stderr=str(e))
    print(f"configured {len(paths)} Claude mem0 plugin config(s); restart Claude Code", file=sys.stderr)
    return subprocess.CompletedProcess(args=["mem0-local"], returncode=0)


def _repo_root() -> Path:
    # tools/aipc_lib/tools_menu.py → repo root
    return Path(__file__).resolve().parents[2]


def _codexbar_usage_installed() -> bool:
    if _has("aipc-usage"):
        return True
    try:
        import codexbar_usage  # noqa: F401

        return True
    except ImportError:
        return False


def _install_codexbar_usage() -> subprocess.CompletedProcess:
    pkg = _repo_root() / "modules/dev-ai-codexbar-usage/files/usr/lib/aipc-codexbar-usage"
    if not pkg.is_dir():
        return subprocess.CompletedProcess(
            args=["codexbar-usage"],
            returncode=1,
            stderr=f"package tree missing: {pkg}",
        )
    return _run([sys.executable, "-m", "pip", "install", "--user", "-e", str(pkg)])


def _uninstall_codexbar_usage() -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "pip", "uninstall", "-y", "aipc-codexbar-usage"])


def _codexbar_gui_installed() -> bool:
    if _has("codexbar-gui"):
        return True
    try:
        import codexbar_gui  # noqa: F401

        return True
    except ImportError:
        return False


def _install_codexbar_gui() -> subprocess.CompletedProcess:
    pkg = _repo_root() / "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui"
    if not pkg.is_dir():
        return subprocess.CompletedProcess(
            args=["codexbar-gui"],
            returncode=1,
            stderr=f"package tree missing: {pkg}",
        )
    return _run([sys.executable, "-m", "pip", "install", "--user", "-e", str(pkg)])


def _uninstall_codexbar_gui() -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "pip", "uninstall", "-y", "codexbar-gui"])


CATEGORIES: dict[str, list[Tool]] = {
    "AI coding tools": [
        Tool("aider", lambda: _has("aider"), _install_aider, _uninstall_aider),
        Tool(
            "cline (VSCode)",
            lambda: _vscode_ext_installed("saoudrizwan.claude-dev"),
            _install_cline,
            _uninstall_cline,
        ),
        Tool(
            "continue (VSCode)",
            lambda: _vscode_ext_installed("Continue.continue"),
            _install_continue,
            _uninstall_continue,
        ),
        Tool("goose", lambda: _has("goose"), _install_goose, _uninstall_goose),
        Tool("opencode", _opencode_installed, _install_opencode, _uninstall_opencode),
        Tool(
            "mem0 local service",
            _mem0_local_service_configured,
            _configure_mem0_local_service,
            _configure_mem0_local_service,
            install_label="Configure Claude",
            uninstall_label="Re-apply Claude",
            uninstall_marks_absent=False,
        ),
        Tool(
            "codexbar usage (aipc-usage)",
            _codexbar_usage_installed,
            _install_codexbar_usage,
            _uninstall_codexbar_usage,
        ),
        Tool(
            "codexbar GUI",
            _codexbar_gui_installed,
            _install_codexbar_gui,
            _uninstall_codexbar_gui,
        ),
    ],
    "Terminal": [
        Tool("ccstatus", lambda: _has("ccstatus"), _install_ccstatus, _uninstall_ccstatus),
    ],
}
