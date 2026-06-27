from __future__ import annotations

import os
import subprocess
from pathlib import Path

_DEFAULT_KEY = "/etc/aipc/age.key"


def _env() -> dict[str, str]:
    key_file = os.environ.get("AIPC_AGE_KEY_FILE", _DEFAULT_KEY)
    env = os.environ.copy()
    if Path(key_file).exists():
        env["SOPS_AGE_KEY_FILE"] = key_file
    return env


def view(path: str) -> None:
    subprocess.run(["sops", "--decrypt", path], env=_env(), check=True)


def edit(path: str) -> None:
    subprocess.run(["sops", path], env=_env(), check=True)
