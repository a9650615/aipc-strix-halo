"""aipc-rag-screen-audio — opt-in screen OCR + audio transcript capture.

What's real here: consent/TTL gating, pause-on-voice-mute, and the TTL
purge of old captures — none of that depends on anything unbuilt.

What's NOT implemented: the actual OCR (Lemonade ONNX) and audio-transcript
(Phase 3 voice-stt-paraformer) capture calls. Per the proposal's own Q2,
this watcher is expected to stay idle until Phase 3 ships; Lemonade's OCR
model/endpoint choice is also still an open "pick a mature option, propose
it" item (not decided here). Implementing capture now would mean guessing
both of those, so this idles and logs instead of guessing.
"""

import subprocess
from pathlib import Path

import psycopg2
import yaml

from aipc_rag.common import PG_DSN, get_logger, run_forever

CONFIG = Path("/etc/aipc/rag/screen-audio.yaml")
SOURCE = "screen-audio"
INTERVAL_S = 3600


log = get_logger(__name__)


def load_config() -> dict:
    if not CONFIG.exists():
        return {"enabled": False, "ttl_days": 7}
    return yaml.safe_load(CONFIG.read_text()) or {"enabled": False, "ttl_days": 7}


def voice_muted() -> bool:
    proc = subprocess.run(
        ["systemctl", "is-active", "--quiet", "aipc-voice-mute.target"],
        check=False,
    )
    return proc.returncode == 0


def purge_expired(ttl_days: int) -> None:
    with psycopg2.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM rag_chunks WHERE source = %s AND updated_at < now() - (%s || ' days')::interval",
            (SOURCE, ttl_days),
        )
        conn.commit()


def cycle() -> None:
    config = load_config()
    if not config.get("enabled", False):
        log.info("screen+audio capture not opted in, idling")
        return
    if voice_muted():
        log.info("aipc-voice-mute.target active, pausing this cycle")
        return

    purge_expired(config.get("ttl_days", 7))

    # ponytail: capture+OCR+transcribe not implemented — see module
    # docstring. Upgrade path: implement once Phase 3 (voice-stt-paraformer)
    # exists and a Lemonade OCR model is chosen.
    log.info("screen+audio opted in, but capture/OCR/transcribe not implemented yet")


def main() -> None:
    run_forever(INTERVAL_S, cycle)


if __name__ == "__main__":
    main()
