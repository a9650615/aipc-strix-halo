from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    env = os.environ.get("AIPC_CHATGPT_DATA", "").strip() or os.environ.get(
        "AIPC_WEB_DATA", ""
    ).strip()
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg) / "aipc-web"
    return Path.home() / ".local" / "share" / "aipc-web"


def sites_config_path() -> Path:
    env = os.environ.get("AIPC_WEB_SITES_CONFIG", "").strip()
    if env:
        return Path(env)
    for p in (
        Path("/etc/aipc/assistant/sites.yaml"),
        Path(__file__).resolve().parents[2] / "etc" / "aipc" / "assistant" / "sites.yaml",
        Path(__file__).resolve().parents[4]
        / "etc"
        / "aipc"
        / "assistant"
        / "sites.yaml",
    ):
        if p.is_file():
            return p
    return Path("/etc/aipc/assistant/sites.yaml")


def profile_dir(site_id: str = "default") -> Path:
    env = os.environ.get("AIPC_CHATGPT_PROFILE", "").strip()
    if env and site_id in ("default", "chatgpt"):
        return Path(env)
    return data_root() / "sites" / site_id / "profile"


def storage_state_path(site_id: str = "default") -> Path:
    env = os.environ.get("AIPC_CHATGPT_STORAGE_STATE", "").strip()
    if env and site_id in ("default", "chatgpt"):
        return Path(env)
    return data_root() / "sites" / site_id / "storage_state.json"


def cdp_port() -> int:
    return int(os.environ.get("AIPC_CHATGPT_CDP_PORT", os.environ.get("AIPC_WEB_CDP_PORT", "9222")))
