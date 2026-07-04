from __future__ import annotations

import json
from pathlib import Path

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest
from aipc_lib.opencode_sync import DEFAULT_LITELLM_BASE, NON_CHAT_ALIASES, fetch_model_ids

DEFAULT_CCS_SETTINGS = Path.home() / ".ccs" / "aipc.settings.json"

# CCS's aipc profile is local-model-only (see modules/ccs/README.md) — never
# touches the paid Claude subscription/API, so cloud aliases (main-cloud,
# coder-cloud, ...) are deliberately left out of ANTHROPIC_EXTRA_MODELS,
# same reasoning as the original hand-run `ccs api create --extra-models`.


def sync_extra_models(
    settings_path: Path = DEFAULT_CCS_SETTINGS,
    base_url: str = DEFAULT_LITELLM_BASE,
    manifest_path: Path = DEFAULT_MANIFEST,
    exclude: set[str] = NON_CHAT_ALIASES,
) -> list[str]:
    """Rewrite settings_path's env.ANTHROPIC_EXTRA_MODELS to match LiteLLM's
    current local-only model list (minus *exclude* and whichever alias is
    already the default ANTHROPIC_MODEL). Returns the list of extra model
    ids written.

    Does NOT touch ANTHROPIC_MODEL or the DEFAULT_OPUS/SONNET/HAIKU_MODEL
    keys — that's config_menu.py's tier-switcher's job, a separate concern.

    Requires settings_path to already exist: CCS's settings.json has its
    own schema version/migration counter (see modules/ccs/README.md) — hand-
    synthesizing one from scratch risks drifting out of sync with whatever
    CCS version is actually installed. Run `ccs api create` once first.
    """
    if not settings_path.exists():
        raise FileNotFoundError(
            f"{settings_path} not found — run `ccs api create` first "
            "(see modules/ccs/README.md)"
        )

    all_ids = fetch_model_ids(base_url)
    by_alias = {e.alias: e for e in load_manifest(manifest_path)}

    settings = json.loads(settings_path.read_text())
    env = settings.setdefault("env", {})
    default_model = env.get("ANTHROPIC_MODEL", "")

    extra_ids = [
        mid
        for mid in all_ids
        if mid not in exclude
        and mid != default_model
        and not (by_alias.get(mid) is not None and by_alias[mid].is_cloud)
    ]
    if not extra_ids:
        raise ValueError(f"{base_url}/v1/models returned no local models besides the default")

    env["ANTHROPIC_EXTRA_MODELS"] = ",".join(extra_ids)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return extra_ids
