from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from aipc_chatgpt.paths import sites_config_path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def load_sites_config(path: Path | None = None) -> dict[str, Any]:
    p = path or sites_config_path()
    if not p.is_file():
        return {
            "default_site": "chatgpt",
            "sites": {
                "chatgpt": {
                    "enabled": True,
                    "title": "ChatGPT",
                    "url": "https://chatgpt.com/",
                    "pack": "aipc_chatgpt.sites.chatgpt",
                }
            },
            "setup": {"use_llm": True, "model": "resident-small"},
        }
    if yaml is None:
        raise RuntimeError("PyYAML required to load sites.yaml")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def list_site_ids(cfg: dict[str, Any] | None = None) -> list[str]:
    cfg = cfg or load_sites_config()
    sites = cfg.get("sites") or {}
    return [k for k, v in sites.items() if isinstance(v, dict) and v.get("enabled", True)]


def get_site_config(site_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_sites_config()
    sites = cfg.get("sites") or {}
    if site_id not in sites:
        raise KeyError(f"unknown site {site_id!r}; known={list(sites)}")
    return dict(sites[site_id])


def load_pack(site_id: str, cfg: dict[str, Any] | None = None) -> Any:
    sc = get_site_config(site_id, cfg)
    pack_path = sc.get("pack") or f"aipc_chatgpt.sites.{site_id}"
    return importlib.import_module(str(pack_path))


def default_site_id(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or load_sites_config()
    return str(cfg.get("default_site") or "chatgpt")
