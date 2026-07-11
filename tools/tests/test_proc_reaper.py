"""proc_reaper reaps the whole process group, not just the direct child.

Regression for the stuck-Hermes-turn bug: orchestrator spawns
`runuser -- hermes`, so a plain proc.kill() orphaned the grandchild worker.
No hardware; pure process control.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MOD = REPO / "modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/proc_reaper.py"


def _load():
    loader = SourceFileLoader("proc_reaper", str(MOD))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_self_test_runs() -> None:
    proc = subprocess.run([sys.executable, str(MOD)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout


def test_terminate_tree_reaps_grandchild() -> None:
    reaper = _load()
    # sh (parent) forks a `sleep` grandchild that would be orphaned by proc.kill()
    proc = subprocess.Popen(
        ["/bin/sh", "-c", "sleep 60 & echo $! ; wait"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    child_pid = int(proc.stdout.readline().strip())
    assert _alive(child_pid)

    reaper.terminate_tree(proc, grace=2.0)

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and (_alive(child_pid) or proc.poll() is None):
        time.sleep(0.02)
    assert proc.poll() is not None, "parent not reaped"
    assert not _alive(child_pid), "grandchild survived — group kill failed"


def test_already_dead_is_noop() -> None:
    reaper = _load()
    proc = subprocess.Popen(["/bin/true"], start_new_session=True)
    proc.wait()
    reaper.terminate_tree(proc)  # must not raise
