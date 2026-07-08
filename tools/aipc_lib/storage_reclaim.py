from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable

CONFIRM_PHRASE = "reclaim AIPC_LIVE"


@dataclass(frozen=True)
class Step:
    args: list[str]


@dataclass(frozen=True)
class Plan:
    allowed: bool
    reason: str
    steps: list[Step]


def _parts(lsblk: dict) -> list[dict]:
    out: list[dict] = []
    for disk in lsblk.get("blockdevices", []):
        for part in disk.get("children", []) or []:
            if part.get("type") == "part":
                item = dict(part)
                item["disk"] = disk.get("path") or f"/dev/{disk.get('name')}"
                out.append(item)
    return out


def build_plan(lsblk: dict, root_part: str, root_fstype: str) -> Plan:
    parts = _parts(lsblk)
    live = [p for p in parts if p.get("label") == "AIPC_LIVE"]
    if len(live) != 1:
        return Plan(False, f"expected exactly one AIPC_LIVE partition, found {len(live)}", [])

    live_part = live[0]
    root = next((p for p in parts if p.get("path") == root_part), None)
    if root is None:
        return Plan(False, f"root partition {root_part} not found", [])

    if live_part.get("disk") != root.get("disk"):
        return Plan(False, f"AIPC_LIVE is on {live_part.get('disk')}, but root is on {root.get('disk')}", [])

    # A partition grows toward its end, never back across its start, so
    # AIPC_LIVE must sit immediately after root to be reclaimable. R6b installs
    # place it there (install-windows-direct); pre-fix layouts stranded it.
    if live_part.get("partn") != root.get("partn") + 1:
        return Plan(False, "AIPC_LIVE is not immediately after the root partition", [])

    disk = root["disk"]
    steps = [
        Step(["parted", "-s", disk, "rm", str(live_part["partn"])]),
        Step(["parted", "-s", disk, "resizepart", str(root["partn"]), "100%"]),
        Step(["partprobe", disk]),
    ]
    if root_fstype == "btrfs":
        steps.append(Step(["btrfs", "filesystem", "resize", "max", "/"]))
    elif root_fstype in {"ext4", "xfs"}:
        steps.append(Step(["resize2fs" if root_fstype == "ext4" else "xfs_growfs", "/"]))
    else:
        return Plan(False, f"unsupported root filesystem: {root_fstype}", [])
    return Plan(True, "AIPC_LIVE can be reclaimed", steps)


def _json(args: list[str]) -> dict:
    return json.loads(subprocess.check_output(args, text=True))


def _findmnt(field: str, mount: str) -> str:
    return subprocess.check_output(["findmnt", "-n", "-o", field, mount], text=True).strip()


def _resolve_root_device(
    findmnt: Callable[[str, str], str] = _findmnt,
) -> tuple[str, str]:
    # On an ostree/composefs host, findmnt SOURCE / returns the literal
    # "composefs" overlay rather than the backing block device. Walk the real
    # mount points — /sysroot (ostree) → /var (bazzite bind) → / (plain host) —
    # and take the first whose SOURCE is a /dev/ path, stripping any btrfs
    # subvolume suffix (e.g. /dev/nvme0n1p9[/root] → /dev/nvme0n1p9).
    for mnt in ("/sysroot", "/var", "/"):
        try:
            src = findmnt("SOURCE", mnt)
        except subprocess.CalledProcessError:
            continue
        if src.startswith("/dev/"):
            return src.split("[", 1)[0], findmnt("FSTYPE", mnt)
    raise RuntimeError("no block-device backed mount found for root")


def load_plan() -> Plan:
    root, fstype = _resolve_root_device()
    return build_plan(_json(["lsblk", "-J", "-O"]), root, fstype)


def run_reclaim(
    confirm: bool,
    input_func: Callable[[str], str] = input,
    runner: Callable[[list[str], bool], object] = subprocess.run,
) -> int:
    plan = load_plan()
    if not plan.allowed:
        print(plan.reason)
        return 1

    for step in plan.steps:
        print(" ".join(step.args))

    if not confirm:
        return 0

    if input_func(f"Type {CONFIRM_PHRASE!r} to continue: ") != CONFIRM_PHRASE:
        print("confirmation mismatch")
        return 1

    for step in plan.steps:
        runner(step.args, True)
    return 0
