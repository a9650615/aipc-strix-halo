from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest
from aipc_lib.modules import Module

LITELLM_DEFAULT_ENDPOINT = "http://127.0.0.1:4000"

STATUS_OK = "OK"
STATUS_OPTIONAL = "OPTIONAL"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"


@dataclass
class Result:
    module: str
    status: str  # STATUS_OK | STATUS_OPTIONAL | STATUS_FAIL | STATUS_WARN
    message: str

    @property
    def ok(self) -> bool:
        # ponytail: back-compat shim; callers (CLI) still branch on ok
        return self.status in (STATUS_OK, STATUS_OPTIONAL, STATUS_WARN)


def run_all(mods: list[Module]) -> list[Result]:
    results: list[Result] = []
    for m in mods:
        verify = m.path / "verify.sh"
        if not verify.exists():
            results.append(Result(module=m.name, status=STATUS_OK, message="no verify.sh; skipped"))
            continue
        proc = subprocess.run(
            ["/bin/sh", str(verify)],
            capture_output=True,
            text=True,
        )
        msg = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0:
            results.append(Result(module=m.name, status=STATUS_OK, message=msg or "ok"))
        elif proc.returncode == 2:
            # ponytail: exit 2 = intentionally disabled optional module (e.g. llm-vllm)
            results.append(
                Result(module=m.name, status=STATUS_OPTIONAL, message=msg or "disabled (optional)")
            )
        else:
            results.append(Result(module=m.name, status=STATUS_FAIL, message=msg or "failed"))
    return results


def check_gateway_aliases(
    manifest_path: Path = DEFAULT_MANIFEST,
    endpoint: str = LITELLM_DEFAULT_ENDPOINT,
) -> Result | None:
    """Compare models.yaml aliases against LiteLLM /v1/models.

    Returns None if the manifest doesn't exist (llm-models not installed).
    Returns a WARN result if the gateway isn't reachable (not yet installed).
    Returns FAIL listing missing aliases if any are absent from the gateway.
    """
    entries = load_manifest(manifest_path)
    if not entries:
        return None

    url = f"{endpoint.rstrip('/')}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.URLError:
        # ponytail: gateway not running is a warning, not a fail — may not be installed yet
        return Result(
            module="litellm-aliases",
            status=STATUS_WARN,
            message=f"gateway unreachable at {endpoint}",
        )

    served = {item.get("id") for item in payload.get("data", []) if isinstance(item, dict)}
    missing = [e.alias for e in entries if e.alias not in served]
    if missing:
        return Result(
            module="litellm-aliases",
            status=STATUS_FAIL,
            message="missing from gateway: " + ", ".join(missing),
        )
    return Result(
        module="litellm-aliases",
        status=STATUS_OK,
        message=f"{len(entries)} aliases served",
    )
