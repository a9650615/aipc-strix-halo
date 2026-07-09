from __future__ import annotations

import os
from pathlib import Path

# Prefer installed paths; fall back to module tree for dev/self-test.
_MODULE_ETC = Path(__file__).resolve().parents[2] / "etc" / "aipc" / "assistant"
_INSTALL_ETC = Path("/etc/aipc/assistant")


def etc_dir() -> Path:
    env = os.environ.get("AIPC_ASSISTANT_ETC", "").strip()
    if env:
        return Path(env)
    if _INSTALL_ETC.is_dir() and (_INSTALL_ETC / "mode").exists():
        return _INSTALL_ETC
    if _MODULE_ETC.is_dir():
        return _MODULE_ETC
    return _INSTALL_ETC


def mode_path() -> Path:
    return etc_dir() / "mode"


def keywords_path() -> Path:
    return etc_dir() / "keywords.yaml"


def features_path() -> Path:
    return etc_dir() / "features.yaml"


def controller_path() -> Path:
    return etc_dir() / "controller.yaml"


def inject_policy_path() -> Path:
    return etc_dir() / "inject-policy.yaml"
