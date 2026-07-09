"""Configuration loader for CodexBar GUI."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("codexbar_gui.config")


if __import__("sys").version_info >= (3, 11):
    import yaml
else:
    try:
        import yaml
    except ImportError:
        yaml = None


@dataclasses.dataclass
class ProgressBarConfig:
    shape: str = "rounded"
    bar_height: int = 8
    corner_radius: int = 4
    show_labels: bool = True
    theme: str = "auto"


@dataclasses.dataclass
class TooltipConfig:
    show_usage: bool = True
    show_cost: bool = True
    show_identity: bool = True


@dataclasses.dataclass
class GuiConfig:
    refresh_interval: int = 60
    enabled_providers: List[str] = dataclasses.field(default_factory=list)
    icon_size: int = 22
    progress_bar: ProgressBarConfig = dataclasses.field(
        default_factory=ProgressBarConfig
    )
    tooltip: TooltipConfig = dataclasses.field(default_factory=TooltipConfig)


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(path: Optional[Path] = None) -> GuiConfig:
    """Load config from system defaults + optional user override.

    Priority (high to low): user config > system defaults > hardcoded defaults.
    """
    system_config = _load_yaml(Path("/etc/aipc/codexbar-gui/config.yaml"))
    user_config = {}
    if path and path.is_file():
        user_config = _load_yaml(path)

    merged = _merge(system_config, user_config)

    return GuiConfig(
        refresh_interval=int(merged.get("refresh_interval", 60)),
        enabled_providers=merged.get("enabled_providers", []),
        icon_size=int(merged.get("icon_size", 22)),
        progress_bar=ProgressBarConfig(
            shape=merged.get("progress_bar", {}).get("shape", "rounded"),
            bar_height=int(merged.get("progress_bar", {}).get("bar_height", 8)),
            corner_radius=int(merged.get("progress_bar", {}).get("corner_radius", 4)),
            show_labels=merged.get("progress_bar", {}).get("show_labels", True),
            theme=merged.get("progress_bar", {}).get("theme", "auto"),
        ),
        tooltip=TooltipConfig(
            show_usage=merged.get("tooltip", {}).get("show_usage", True),
            show_cost=merged.get("tooltip", {}).get("show_cost", True),
            show_identity=merged.get("tooltip", {}).get("show_identity", True),
        ),
    )


def _load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        return {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.debug("Failed to load yaml %s: %s", path, e)
        return {}
