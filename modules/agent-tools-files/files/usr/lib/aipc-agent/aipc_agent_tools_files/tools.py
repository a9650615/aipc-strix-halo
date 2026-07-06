"""File-IO tools for agent sub-agents (phase-4-agent#4.1).

Every path passed to read_file/write_file/list_dir/delete is resolved
(realpath, symlinks followed) and checked against the allowlist BEFORE any
filesystem syscall touches it. A path that resolves outside every
allowlisted root is rejected with AllowlistViolation — never silently
clamped into the workspace.

roots[0] is the "workspace": delete works there directly. Deleting a path
that only resolves inside a later root requires a grant from
`aipc-agent-gate` (phase-4-agent#5.1). That daemon doesn't exist yet —
check_gate_grant() fails closed (denies) until it does. See its docstring.
"""

import json
import socket
from pathlib import Path

DEFAULT_ALLOWLIST_CONFIG = "/etc/aipc/agent-tools/files-allowlist.conf"
DEFAULT_ROOT = "/var/lib/aipc-agent/workspace"
GATE_SOCKET = "/run/aipc-agent-gate.sock"


class AllowlistViolation(PermissionError):
    """A path resolved outside every allowlisted root."""


def _load_roots(config_path: str = DEFAULT_ALLOWLIST_CONFIG) -> list[Path]:
    roots = []
    try:
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    roots.append(line)
    except FileNotFoundError:
        pass
    if not roots:
        roots = [DEFAULT_ROOT]
    return [Path(r).expanduser().resolve(strict=False) for r in roots]


def _check_allowed(path: str, roots: list[Path] | None = None) -> Path:
    roots = roots if roots is not None else _load_roots()
    resolved = Path(path).expanduser().resolve(strict=False)
    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved
    raise AllowlistViolation(
        f"path {path!r} resolves to {resolved}, which is outside the "
        f"allowlisted roots {[str(r) for r in roots]}"
    )


def read_file(path: str, roots: list[Path] | None = None) -> str:
    resolved = _check_allowed(path, roots)
    return resolved.read_text()


def write_file(path: str, content: str, roots: list[Path] | None = None) -> None:
    resolved = _check_allowed(path, roots)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)


def list_dir(path: str, roots: list[Path] | None = None) -> list[str]:
    resolved = _check_allowed(path, roots)
    return sorted(str(p) for p in resolved.iterdir())


def check_gate_grant(action: str, sock_path: str = GATE_SOCKET) -> bool:
    """Ask aipc-agent-gate whether `action` is currently granted.

    Wire protocol (phase-4-agent#5.1, modules/agent-gate/): newline-
    delimited JSON request/response over the UNIX socket --
    {"cmd": "check", "action": ...} -> {"allowed": bool, "grant_id": ...}.
    Any connection failure (missing socket, refused, timeout) or malformed
    response is treated as "no grant" — fail closed, not fail open.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(sock_path)
            s.sendall((json.dumps({"cmd": "check", "action": action}) + "\n").encode())
            resp = s.recv(4096)
            return bool(json.loads(resp).get("allowed", False))
    except (OSError, ValueError):
        return False


def delete(path: str, roots: list[Path] | None = None) -> None:
    roots = roots if roots is not None else _load_roots()
    resolved = _check_allowed(path, roots)
    workspace = roots[0]
    in_workspace = resolved == workspace or workspace in resolved.parents
    if not in_workspace and not check_gate_grant("files.delete"):
        raise PermissionError(
            f"delete outside workspace root {workspace} requires an "
            f"aipc-agent-gate grant for 'files.delete'; none was granted "
            f"(gate not wired up yet, see phase-4-agent#5.1)"
        )
    if resolved.is_dir():
        resolved.rmdir()  # ponytail: non-recursive only; add rmtree if a sub-agent needs it
    else:
        resolved.unlink()


def self_test() -> None:
    """ponytail: one runnable check — allowlist accept/reject, traversal,
    symlink escape, and gate fail-closed delete."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        other_root = tmp_path / "other"
        other_root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        roots = [workspace, other_root]

        write_file(str(workspace / "a.txt"), "hello", roots=roots)
        assert read_file(str(workspace / "a.txt"), roots=roots) == "hello"
        assert str(workspace / "a.txt") in list_dir(str(workspace), roots=roots)

        # path traversal must be rejected before any syscall runs
        (outside / "passwd").write_text("root:x:0:0")
        traversal = str(workspace / ".." / "outside" / "passwd")
        try:
            read_file(traversal, roots=roots)
            raise AssertionError("path traversal was NOT rejected")
        except AllowlistViolation:
            pass

        # symlink escape must also be rejected (resolve() follows symlinks)
        link = workspace / "escape"
        link.symlink_to(outside / "passwd")
        try:
            read_file(str(link), roots=roots)
            raise AssertionError("symlink escape was NOT rejected")
        except AllowlistViolation:
            pass

        # delete inside workspace (roots[0]): no gate needed
        delete(str(workspace / "a.txt"), roots=roots)
        assert not (workspace / "a.txt").exists()

        # delete inside a non-workspace allowlisted root: gate doesn't
        # exist yet -> must fail closed, file must survive
        other_file = other_root / "b.txt"
        other_file.write_text("x")
        try:
            delete(str(other_file), roots=roots)
            raise AssertionError("delete outside workspace was NOT gated")
        except PermissionError:
            pass
        assert other_file.exists()

    print("self-test passed")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
