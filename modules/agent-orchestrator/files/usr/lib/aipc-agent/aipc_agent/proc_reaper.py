"""Reap a subprocess AND its descendants.

The orchestrator spawns Hermes via `runuser -u <user> -- hermes …` when it runs
as root, so `proc` is the `runuser` wrapper and the real hermes worker is a
grandchild. A plain `proc.kill()` kills only `runuser` and orphans the worker,
which then keeps hammering the model for the whole turn (observed: a voice turn
stuck ~16 min after its timeout was already logged). Spawn children with
`start_new_session=True` and reap the whole process group here.
"""

from __future__ import annotations

import os
import signal
import subprocess


def terminate_tree(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """SIGTERM then SIGKILL the child's whole process group; never raises.

    Requires the child to have been started with `start_new_session=True` so it
    leads its own group. Falls back to signalling just `proc` if the group id
    cannot be resolved (e.g. the child already exited)."""
    if proc.poll() is not None:
        return
    try:
        pgid: int | None = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError, OSError):
        pgid = None

    def _send(sig: int) -> None:
        if pgid is not None:
            try:
                os.killpg(pgid, sig)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass

    _send(signal.SIGTERM)
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    _send(signal.SIGKILL)
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _self_test() -> int:
    # A grandchild (sleep) that outlives its parent shell unless the whole group
    # is reaped — mirrors runuser→hermes→llama-client.
    proc = subprocess.Popen(
        ["/bin/sh", "-c", "sleep 60 & echo $! ; wait"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert proc.stdout is not None
    child_pid = int(proc.stdout.readline().strip())
    assert _alive(child_pid), "grandchild should be running"
    terminate_tree(proc, grace=2.0)
    # give the kernel a beat to deliver signals
    for _ in range(50):
        if not _alive(child_pid) and proc.poll() is not None:
            break
        _sleep_briefly()
    assert proc.poll() is not None, "parent should be reaped"
    assert not _alive(child_pid), "grandchild should be reaped with the group"
    # already-dead proc is a no-op, no raise
    terminate_tree(proc)
    print("proc_reaper: self-test OK")
    return 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except OSError:
        return False
    return True


def _sleep_briefly() -> None:
    import time

    time.sleep(0.02)


if __name__ == "__main__":
    raise SystemExit(_self_test())
