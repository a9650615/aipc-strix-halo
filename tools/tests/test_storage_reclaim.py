from __future__ import annotations

import subprocess

from click.testing import CliRunner

from aipc_lib import storage_reclaim
from aipc_lib.cli import main


def _disk(children: list[dict]) -> dict:
    return {"blockdevices": [{"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "children": children}]}


def _part(n: int, label: str | None = None, pkname: str = "nvme0n1") -> dict:
    return {
        "name": f"nvme0n1p{n}",
        "path": f"/dev/nvme0n1p{n}",
        "type": "part",
        "label": label,
        "pkname": pkname,
        "fstype": "btrfs" if label is None else "vfat",
        "partn": n,
        "mountpoints": ["/sysroot"] if label is None else [],
    }


def test_plan_refuses_missing_live_partition() -> None:
    plan = storage_reclaim.build_plan(_disk([_part(2)]), "/dev/nvme0n1p2", "btrfs")

    assert not plan.allowed
    assert plan.reason == "expected exactly one AIPC_LIVE partition, found 0"


def test_plan_refuses_duplicate_live_partitions() -> None:
    plan = storage_reclaim.build_plan(_disk([_part(2), _part(3, "AIPC_LIVE"), _part(4, "AIPC_LIVE")]), "/dev/nvme0n1p2", "btrfs")

    assert not plan.allowed
    assert plan.reason == "expected exactly one AIPC_LIVE partition, found 2"


def test_plan_refuses_live_on_different_disk() -> None:
    lsblk = {
        "blockdevices": [
            {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "children": [_part(2)]},
            {"name": "sda", "path": "/dev/sda", "type": "disk", "children": [_part(1, "AIPC_LIVE", pkname="sda")]},
        ]
    }

    plan = storage_reclaim.build_plan(lsblk, "/dev/nvme0n1p2", "btrfs")

    assert not plan.allowed
    assert plan.reason == "AIPC_LIVE is on /dev/sda, but root is on /dev/nvme0n1"


def test_plan_refuses_non_adjacent_live_partition() -> None:
    plan = storage_reclaim.build_plan(_disk([_part(2), _part(4, "AIPC_LIVE")]), "/dev/nvme0n1p2", "btrfs")

    assert not plan.allowed
    assert plan.reason == "AIPC_LIVE is not immediately after the root partition"


def test_plan_allows_adjacent_live_partition() -> None:
    plan = storage_reclaim.build_plan(_disk([_part(2), _part(3, "AIPC_LIVE")]), "/dev/nvme0n1p2", "btrfs")

    assert plan.allowed
    assert [step.args for step in plan.steps] == [
        ["parted", "-s", "/dev/nvme0n1", "rm", "3"],
        ["parted", "-s", "/dev/nvme0n1", "resizepart", "2", "100%"],
        ["partprobe", "/dev/nvme0n1"],
        ["btrfs", "filesystem", "resize", "max", "/"],
    ]


def test_dry_run_does_not_execute_destructive_commands(monkeypatch) -> None:
    plan = storage_reclaim.build_plan(_disk([_part(2), _part(3, "AIPC_LIVE")]), "/dev/nvme0n1p2", "btrfs")
    calls: list[list[str]] = []

    monkeypatch.setattr(storage_reclaim, "load_plan", lambda: plan)

    rc = storage_reclaim.run_reclaim(confirm=False, runner=lambda args, check: calls.append(args))

    assert rc == 0
    assert calls == []


def test_confirm_requires_typed_phrase(monkeypatch) -> None:
    plan = storage_reclaim.build_plan(_disk([_part(2), _part(3, "AIPC_LIVE")]), "/dev/nvme0n1p2", "btrfs")
    calls: list[list[str]] = []

    monkeypatch.setattr(storage_reclaim, "load_plan", lambda: plan)

    rc = storage_reclaim.run_reclaim(confirm=True, input_func=lambda _: "no", runner=lambda args, check: calls.append(args))

    assert rc == 1
    assert calls == []


def test_cli_reclaim_live_defaults_to_dry_run(monkeypatch) -> None:
    seen = []

    def fake_run(confirm: bool) -> int:
        seen.append(confirm)
        return 0

    monkeypatch.setattr(storage_reclaim, "run_reclaim", fake_run)

    result = CliRunner().invoke(main, ["storage", "reclaim-live"])

    assert result.exit_code == 0
    assert seen == [False]


def test_cli_reclaim_live_propagates_failure(monkeypatch) -> None:
    monkeypatch.setattr(storage_reclaim, "run_reclaim", lambda confirm: 7)

    result = CliRunner().invoke(main, ["storage", "reclaim-live", "--confirm"])

    assert result.exit_code == 7
