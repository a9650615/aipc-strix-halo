from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest
from aipc_lib.modules import Module

LITELLM_DEFAULT_ENDPOINT = "http://127.0.0.1:4000"
DEFAULT_BACKEND_FILE = Path("/etc/aipc/memory/backend")
VECTOR_COUNT_WARN_THRESHOLD = 1_000_000
_BACKEND_SERVICES = {"pgvector": "postgres.service", "qdrant": "qdrant.service"}

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


def check_active_backend(backend_file: Path = DEFAULT_BACKEND_FILE) -> Result | None:
    """Confirm whichever vector backend systemd unit is actually running
    matches `/etc/aipc/memory/backend`'s declared value.

    Returns None if the backend file doesn't exist (memory-rag not
    installed). Deployed images don't ship the repo's modules/ source tree,
    so this checks systemd unit state directly rather than module
    .disabled markers (see phase-2-memory#9.1).
    """
    if not backend_file.exists():
        return None

    declared = backend_file.read_text().strip()
    service = _BACKEND_SERVICES.get(declared)
    if service is None:
        return Result(
            module="memory-rag-backend",
            status=STATUS_FAIL,
            message=f"{backend_file} declares unknown backend {declared!r}",
        )

    proc = subprocess.run(["systemctl", "is-active", "--quiet", service], check=False)
    if proc.returncode != 0:
        return Result(
            module="memory-rag-backend",
            status=STATUS_FAIL,
            message=f"declared backend {declared!r} but {service} is not active",
        )
    return Result(module="memory-rag-backend", status=STATUS_OK, message=f"{declared} active")


def check_vector_count(
    dsn: str = "postgresql://postgres@127.0.0.1:5432/aipc",
    threshold: int = VECTOR_COUNT_WARN_THRESHOLD,
) -> Result | None:
    """INFO-level nudge toward `aipc db migrate qdrant` once pgvector's
    rag_chunks table crosses `threshold` rows (phase-2-memory#9.2).

    Returns None if Postgres isn't reachable (not installed/not running —
    same "not everything is hardware yet" reasoning as check_gateway_aliases).
    """
    try:
        import psycopg2

        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM rag_chunks")
            count = cur.fetchone()[0]
    except Exception:
        return None

    if count > threshold:
        return Result(
            module="memory-rag-vectors",
            status=STATUS_WARN,
            message=f"{count} vectors > {threshold} — consider `aipc db migrate qdrant`",
        )
    return Result(module="memory-rag-vectors", status=STATUS_OK, message=f"{count} vectors")


def check_voice_once(
    script: Path = Path("/usr/bin/aipc-voice-once"),
    stt_unit: Path = Path("/etc/systemd/system/aipc-voice-stt-sensevoice.service"),
    notifier: str = "notify-send",
    runner=subprocess.run,
) -> list[Result]:
    results: list[Result] = []
    if not script.exists() or not script.is_file() or not script.stat().st_mode & 0o111:
        return [
            Result(
                module="voice-pipecat",
                status=STATUS_FAIL,
                message=f"{script} missing or not executable",
            )
        ]

    results.append(Result("voice-pipecat", STATUS_OK, f"{script} executable"))

    if not stt_unit.exists():
        results.append(
            Result(
                "voice-stt-sensevoice",
                STATUS_OPTIONAL,
                f"{stt_unit.name} unit not installed; voice STT not enabled on this host",
            )
        )
    else:
        proc = runner(["systemctl", "is-active", "--quiet", stt_unit.name], check=False)
        status = STATUS_OK if proc.returncode == 0 else STATUS_OPTIONAL
        message = (
            f"{stt_unit.name} active"
            if proc.returncode == 0
            else f"{stt_unit.name} installed but not active"
        )
        results.append(Result("voice-stt-sensevoice", status, message))

    if shutil.which(notifier) is None:
        results.append(
            Result(
                "voice-pipecat-notify",
                STATUS_WARN,
                "notify-send not found; replies fall back to stdout",
            )
        )
    else:
        results.append(Result("voice-pipecat-notify", STATUS_OK, "notify-send available"))

    return results
