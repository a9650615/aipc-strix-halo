"""Pure wake policy: classify / arm / thrash / empty-capture (no I/O).

Loaded by aipc_voice_wake and unit-tested in isolation.
"""
from __future__ import annotations

import array
import os
import re
import struct
from pathlib import Path

def preload_wake_policy_file() -> Path | None:
    """Load wake-policy.env into os.environ before knobs bind (file wins)."""
    path = Path(
        os.environ.get("AIPC_WAKE_POLICY_FILE", "/etc/aipc/voice/wake-policy.env")
    )
    if not path.is_file():
        return None
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ[key] = val
        return path
    except OSError as exc:
        print(f"aipc-voice-wake-policy: {path}: {exc}", flush=True)
        return None


POLICY_FILE_LOADED = preload_wake_policy_file()

SAMPLE_RATE = 16000
FRAME_MS = 30
ENERGY_THRESHOLD = float(os.environ.get("AIPC_WAKE_ENERGY", "2800"))
COOLDOWN_S = float(os.environ.get("AIPC_WAKE_COOLDOWN", "10"))
ENERGY_FRAMES = int(os.environ.get("AIPC_WAKE_ENERGY_FRAMES", "8"))
CMD_MAX_S = float(os.environ.get("AIPC_WAKE_CMD_MAX_S", "10"))
CMD_END_SILENCE_MS = int(os.environ.get("AIPC_WAKE_CMD_END_SILENCE_MS", "1100"))
FOLLOWUP_DIRECT = os.environ.get("AIPC_WAKE_FOLLOWUP_DIRECT", "0") not in (
    "0",
    "false",
    "no",
    "off",
)
ALLOW_FUZZY_PROMOTE = os.environ.get("AIPC_WAKE_ALLOW_FUZZY_PROMOTE", "0") not in (
    "0",
    "false",
    "no",
    "off",
)
PROMOTE_SCORE = int(os.environ.get("AIPC_WAKE_PROMOTE_SCORE", "90"))
CANDIDATE_SCORE = int(os.environ.get("AIPC_WAKE_CANDIDATE_SCORE", "70"))
WAKE_SPEECH_MS_MIN = int(os.environ.get("AIPC_WAKE_SPEECH_MS_MIN", "280"))
WAKE_SPEECH_MS_MAX = int(os.environ.get("AIPC_WAKE_SPEECH_MS_MAX", "1400"))
HARD_MIN_SPEECH_MS = int(os.environ.get("AIPC_WAKE_HARD_MIN_SPEECH_MS", "180"))
MAX_REPROMPTS = int(os.environ.get("AIPC_WAKE_MAX_REPROMPTS", "1"))
REPROMPT_TEXT = os.environ.get("AIPC_WAKE_REPROMPT_TEXT", "沒聽清，請再說一次")
MISS_BACKOFF_BASE = float(os.environ.get("AIPC_WAKE_MISS_BACKOFF_BASE", "6"))
MISS_BACKOFF_CAP = float(os.environ.get("AIPC_WAKE_MISS_BACKOFF_CAP", "90"))
FUZZY_PARTICLES = frozenset(
    {
        "我",
        "我呀",
        "我啊",
        "嘿",
        "嗨",
        "黑",
        "咯",
        "咳",
        "嗯",
        "啊",
        "呃",
        "哦",
        "喔",
        "哈",
        "唔",
        "恩",
    }
)
_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)

_WAKE_ALIASES: dict[str, tuple[str, ...]] = {
    "嘿助理": (
        "嘿助理",
        "嗨助理",
        "黑助理",
        "hei助理",
        "he助理",
        "hey助理",
        "heyassistant",
        "hiassistant",
        "helloassistant",
    ),
    "小廢物": (
        "小廢物",
        "小废物",
        "小飞物",
        "小飛物",
        "小飞幕",
        "小飛幕",
        "小废料",
        "小廢料",
    ),
    "hey assistant": (
        "heyassistant",
        "hiassistant",
        "heyjuly",
        "heyjulie",
        "heyjuly",
        "heyjarvis",
    ),
}


def pcm_rms(frame: bytes) -> float:
    if not frame:
        return 0.0
    n = len(frame) // 2
    if n <= 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frame[: n * 2])
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / n) ** 0.5


def norm_text(text: str) -> str:
    t = text.strip().lower()
    t = t.replace("废", "廢").replace("助 理", "助理")
    t = _PUNCT_RE.sub("", t)
    return t


# Compat alias used by wake.py historically
def _norm(text: str) -> str:
    return norm_text(text)


def phrase_hit(transcript: str, phrases: list[str]) -> str | None:
    """Clear wake phrase match only (no particle auto-arm)."""
    from difflib import SequenceMatcher

    hay = norm_text(transcript)
    if not hay or len(hay) < 2:
        return None
    if hay in FUZZY_PARTICLES:
        return None

    for p in sorted(phrases, key=lambda x: len(norm_text(x)), reverse=True):
        n = norm_text(p)
        if len(n) >= 3 and n in hay:
            return p

    alias_map: dict[str, tuple[str, ...]] = {
        "嘿助理": (
            "嘿助理",
            "嗨助理",
            "黑助理",
            "嘿嘴",
            "嘿嘴理",
            "嘿助哩",
            "嘿自理",
            "he助理",
            "hey助理",
            "hei助理",
            "heyassistant",
            "hiassistant",
        ),
        "小廢物": (
            "小廢物",
            "小废物",
            "小飞物",
            "小飛物",
            "小飞幕",
            "小飛幕",
            "小废料",
        ),
        "hey assistant": (
            "heyassistant",
            "hiassistant",
            "heyjulie",
            "heyjarvis",
        ),
        "你好助理": (
            "你好助理",
            "你好助手",
            "您好助理",
        ),
    }
    for label, aliases in {**_WAKE_ALIASES, **alias_map}.items():
        for a in aliases:
            an = norm_text(a)
            if len(an) < 3:
                continue
            if an in hay:
                for p in phrases:
                    pn = norm_text(p)
                    if pn == norm_text(label) or norm_text(label) in pn:
                        return p
                for p in phrases:
                    if "助理" in norm_text(p) and ("助理" in an or "助" in an):
                        return p
                    if "小" in norm_text(p) and an.startswith("小"):
                        return p
                    if "assistant" in norm_text(p) and "assist" in an:
                        return p

    if re.search(r"(嘿|嗨|黑)(助|理|嘴|自)", hay) or re.search(
        r"(hey|hei|hi)(assistant|assist|julie|jarvis)", hay
    ):
        for p in phrases:
            if "助理" in norm_text(p) or "assistant" in norm_text(p):
                return p

    if re.search(r"小.{0,2}(廢|废|飞|飛|物|幕)", hay):
        for p in phrases:
            if "小" in norm_text(p):
                return p

    best_p, best_r = None, 0.0
    for p in phrases:
        n = norm_text(p)
        if len(n) < 3:
            continue
        r = SequenceMatcher(None, n, hay).ratio()
        if abs(len(n) - len(hay)) > 2 and r < 0.9:
            continue
        if r > best_r:
            best_r, best_p = r, p
    if best_p is not None and best_r >= 0.78:
        return best_p
    return None


def classify_wake_text(
    transcript: str, phrases: list[str]
) -> tuple[str, str | None]:
    hay = norm_text(transcript or "")
    if not hay:
        return "none", None
    if hay in FUZZY_PARTICLES:
        return "fuzzy", None
    hit = phrase_hit(transcript, phrases)
    if hit:
        return "clear", hit
    if len(hay) <= 2:
        return "fuzzy", None
    return "none", None


def score_wake_pcm(
    pcm: bytes,
    *,
    noise_floor: float = 500.0,
    thr: float = 2200.0,
    frame_ms: int = FRAME_MS,
) -> int:
    if not pcm or len(pcm) < 4:
        return 0
    frame_bytes = max(2, SAMPLE_RATE * frame_ms // 1000 * 2)
    speech_frames = 0
    total = 0
    peak = 0.0
    for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        total += 1
        r = pcm_rms(pcm[i : i + frame_bytes])
        if r > peak:
            peak = r
        if r >= thr:
            speech_frames += 1
    if total == 0:
        return 0
    speech_ms = speech_frames * frame_ms
    if speech_ms < HARD_MIN_SPEECH_MS:
        return 0
    noise = max(float(noise_floor), 1.0)
    peak_ratio = peak / noise
    duty = speech_frames / float(total)
    dur_ok = 1.0 if WAKE_SPEECH_MS_MIN <= speech_ms <= WAKE_SPEECH_MS_MAX else 0.0

    def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, x))

    score = (
        30.0 * _clamp((speech_ms - 120) / 500.0)
        + 25.0 * _clamp((peak_ratio - 1.3) / 2.0)
        + 15.0 * _clamp((duty - 0.15) / 0.45)
        + 15.0 * dur_ok
        + 15.0 * 0.5
    )
    return int(round(min(100.0, max(0.0, score))))


def decide_wake_arm(
    tier: str,
    score: int,
    *,
    phrase: str | None = None,
    ptt: bool = False,
    allow_fuzzy_promote: bool = ALLOW_FUZZY_PROMOTE,
    promote_score: int = PROMOTE_SCORE,
    candidate_score: int = CANDIDATE_SCORE,
) -> dict:
    if ptt:
        return {
            "arm": True,
            "arm_reason": "ptt",
            "intentional": True,
            "tier": tier or "none",
            "score": int(score),
            "phrase": phrase,
        }
    if tier == "clear" and phrase:
        return {
            "arm": True,
            "arm_reason": "clear_wake",
            "intentional": True,
            "tier": tier,
            "score": int(score),
            "phrase": phrase,
        }
    if tier == "fuzzy":
        if allow_fuzzy_promote and int(score) >= int(promote_score):
            return {
                "arm": True,
                "arm_reason": "fuzzy_promoted",
                "intentional": True,
                "tier": tier,
                "score": int(score),
                "phrase": phrase,
            }
        if int(score) >= int(candidate_score):
            return {
                "arm": False,
                "arm_reason": "candidate",
                "intentional": False,
                "tier": tier,
                "score": int(score),
                "phrase": phrase,
            }
        return {
            "arm": False,
            "arm_reason": "ghost_suppressed",
            "intentional": False,
            "tier": tier,
            "score": int(score),
            "phrase": phrase,
        }
    return {
        "arm": False,
        "arm_reason": "none",
        "intentional": False,
        "tier": tier or "none",
        "score": int(score),
        "phrase": phrase,
    }


def junk_capture_action(
    *,
    intentional: bool,
    reprompt_used: int,
    max_reprompts: int = MAX_REPROMPTS,
) -> str:
    if intentional and int(reprompt_used) < int(max_reprompts):
        return "reprompt"
    return "idle"


def next_mode_after_empty_capture(action: str) -> str:
    if action == "reprompt":
        return "command"
    return "listen"


def miss_backoff_seconds(
    miss_streak: int,
    *,
    base: float | None = None,
    cap: float | None = None,
) -> float:
    b = float(MISS_BACKOFF_BASE if base is None else base)
    c = float(MISS_BACKOFF_CAP if cap is None else cap)
    exp = min(max(0, int(miss_streak) - 2), 5)
    return float(min(c, b * (2**exp)))


def effective_wake_policy() -> dict:
    return {
        "policy_file": str(POLICY_FILE_LOADED) if POLICY_FILE_LOADED else None,
        "allow_fuzzy_promote": bool(ALLOW_FUZZY_PROMOTE),
        "promote_score": int(PROMOTE_SCORE),
        "candidate_score": int(CANDIDATE_SCORE),
        "energy": float(ENERGY_THRESHOLD),
        "energy_frames": int(ENERGY_FRAMES),
        "cooldown_s": float(COOLDOWN_S),
        "miss_backoff_base": float(MISS_BACKOFF_BASE),
        "miss_backoff_cap": float(MISS_BACKOFF_CAP),
        "max_reprompts": int(MAX_REPROMPTS),
        "reprompt_text": REPROMPT_TEXT,
        "cmd_end_silence_ms": int(CMD_END_SILENCE_MS),
        "cmd_max_s": float(CMD_MAX_S),
        "followup_direct": bool(FOLLOWUP_DIRECT),
    }


# Legacy name used by wake.py
_preload_wake_policy_file = preload_wake_policy_file
_POLICY_FILE_LOADED = POLICY_FILE_LOADED
