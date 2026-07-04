from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Trimmed 2026-07-04 to match models.yaml's small deliberate local set —
# coder-fast/coder-strong/coder-thinking (qwen2.5 family) were cut entirely,
# leaving two real coding-capable models rather than a fast/strong/thinking
# spectrum of one family.
TIERS = ["coder-agentic", "ornith-35b"]
_TIER_PATTERN = re.compile(r"\b(?:" + "|".join(TIERS) + r")\b")


@dataclass
class ToolConfig:
    tool: str
    rel_path: str  # relative to $HOME
    # first capture group in the file that names a tier, matched against
    # _TIER_PATTERN — one line is enough since each of these files only
    # ever has one tier-bearing field (unlike opencode/continue, which
    # register all three at once and aren't switched by this menu).
    field_hint: str


# opencode is deliberately excluded: its default is fixed to coder-agentic
# for reliable tool-calling (see dev-ai-opencode README). continue.yaml has
# no single default field — Continue's own UI picks among its registered
# models.
TOOL_CONFIGS = [
    ToolConfig("aider", ".aider.conf.yml", "model:"),
    ToolConfig("cline", ".config/cline/config.yaml", "openAiModelId:"),
    ToolConfig("goose", ".config/goose/profiles.yaml", "processor:"),
]


def installed_configs(home: Path) -> list[tuple[ToolConfig, Path]]:
    """Return (ToolConfig, absolute path) pairs for configs that exist."""
    found = []
    for tc in TOOL_CONFIGS:
        p = home / tc.rel_path
        if p.exists():
            found.append((tc, p))
    return found


def current_tier(path: Path) -> str | None:
    text = path.read_text()
    m = _TIER_PATTERN.search(text)
    return m.group(0) if m else None


def set_tier(path: Path, new_tier: str) -> bool:
    """Replace the first tier-looking token in the file. Returns True if changed."""
    text = path.read_text()
    new_text, count = _TIER_PATTERN.subn(new_tier, text, count=1)
    if count == 0:
        return False
    path.write_text(new_text)
    return True


AI_SERVICES = ["aipc-models-dir.service", "ollama.service", "litellm.service"]


def service_status(services: list[str] = AI_SERVICES) -> dict[str, str]:
    result = {}
    for svc in services:
        proc = subprocess.run(
            ["systemctl", "is-active", svc], capture_output=True, text=True, check=False
        )
        result[svc] = proc.stdout.strip() or "unknown"
    return result


def restart_service(service: str) -> bool:
    proc = subprocess.run(["sudo", "systemctl", "restart", service], check=False)
    return proc.returncode == 0
