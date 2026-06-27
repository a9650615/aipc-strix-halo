from __future__ import annotations

import subprocess
from dataclasses import dataclass
from aipc_lib.modules import Module


@dataclass
class Result:
    module: str
    ok: bool
    message: str


def run_all(mods: list[Module]) -> list[Result]:
    results: list[Result] = []
    for m in mods:
        verify = m.path / "verify.sh"
        if not verify.exists():
            results.append(Result(module=m.name, ok=True, message="no verify.sh; skipped"))
            continue
        proc = subprocess.run(
            ["/bin/sh", str(verify)],
            capture_output=True,
            text=True,
        )
        ok = proc.returncode == 0
        msg = (proc.stdout + proc.stderr).strip() or ("ok" if ok else "failed")
        results.append(Result(module=m.name, ok=ok, message=msg))
    return results
