# Hermes Provider-Aware Compression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes context compression follow the active main provider: online conversations use the active online API/model, while local conversations use local `coder-compact`.

**Architecture:** Keep Hermes' existing `auto` auxiliary resolution for online providers. Add one narrow compression special case in the existing resolver that replaces only a local main model with the configured local compact model. Remove the static local compression endpoint from the home config and make the verified Codex subscription route the Hermes default.

**Tech Stack:** Python 3.11, pytest, Hermes Agent's existing auxiliary resolver, YAML config, Codex OAuth.

## Global Constraints

- Do not expose, copy, or print OAuth/API secrets.
- Preserve the existing untracked `/var/home/birdyo/.hermes/hermes-agent/.install_method`.
- Do not touch the repository's unrelated dirty files.
- Do not add a dependency or endpoint.
- Online routing must not name or call `127.0.0.1:4000`.
- Local routing must use the existing `custom:local` provider and `coder-compact` model.
- Do not run bootc/ansible renders: no repository module is changing.

---

### Task 1: Add failing resolver tests

**Files:**
- Create: `/var/home/birdyo/.hermes/hermes-agent/tests/agent/test_provider_aware_compression.py`

**Interfaces:**
- Consumes: `agent.auxiliary_client._resolve_auto()` with `task="compression"`.
- Produces: Tests for online pass-through, local compact substitution, and non-compression isolation.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import patch

import agent.auxiliary_client as auxiliary_client


def _resolve(main_provider, main_model, task="compression"):
    seen = {}

    def fake_resolve(provider, model, **kwargs):
        seen.update(provider=provider, model=model)
        return object(), model

    config = {"provider": "auto", "model": "auto", "local_model": "coder-compact"}
    with (
        patch.object(auxiliary_client, "_get_auxiliary_task_config", return_value=config),
        patch.object(auxiliary_client, "resolve_provider_client", side_effect=fake_resolve),
        patch.object(auxiliary_client, "_is_provider_unhealthy", return_value=False),
    ):
        client, resolved = auxiliary_client._resolve_auto(
            main_runtime={"provider": main_provider, "model": main_model},
            task=task,
        )
    return client, resolved, seen


def test_online_compression_keeps_active_online_provider_and_model():
    client, resolved, seen = _resolve("openai-codex", "gpt-5.6-luna")

    assert client is not None
    assert resolved == "gpt-5.6-luna"
    assert seen == {"provider": "openai-codex", "model": "gpt-5.6-luna"}


def test_local_compression_uses_dedicated_local_model():
    client, resolved, seen = _resolve("custom:local", "coder-agentic")

    assert client is not None
    assert resolved == "coder-compact"
    assert seen == {"provider": "custom:local", "model": "coder-compact"}


def test_other_auxiliary_tasks_keep_the_local_main_model():
    client, resolved, seen = _resolve(
        "custom:local", "coder-agentic", task="title_generation"
    )

    assert client is not None
    assert resolved == "coder-agentic"
    assert seen == {"provider": "custom:local", "model": "coder-agentic"}
```

- [ ] **Step 2: Run the focused test and confirm the local assertion fails**

Run from the Hermes checkout:

```bash
/var/home/birdyo/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/agent/test_provider_aware_compression.py
```

Expected: one failure in `test_local_compression_uses_dedicated_local_model`; current code passes `coder-agentic` through.

### Task 2: Implement the narrow resolver branch

**Files:**
- Modify: `/var/home/birdyo/.hermes/hermes-agent/agent/auxiliary_client.py` near `_resolve_auto()` main-provider selection.

**Interfaces:**
- Consumes: active main provider/model and `auxiliary.compression.local_model`.
- Produces: the existing `_resolve_auto()` client/model contract.

- [ ] **Step 1: Add the local-only substitution**

Immediately after `main_provider` and `main_model` are resolved, add:

```python
    if task == "compression" and _normalize_aux_provider(main_provider) == "local":
        local_model = str(
            _get_auxiliary_task_config(task).get("local_model") or ""
        ).strip()
        if local_model:
            main_model = local_model
```

Online providers remain unchanged; no online model is hardcoded.

- [ ] **Step 2: Run focused and existing auxiliary tests**

```bash
/var/home/birdyo/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/agent/test_provider_aware_compression.py
/var/home/birdyo/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/agent/test_auxiliary_client.py tests/agent/test_auxiliary_config_bridge.py
```

Expected: both commands exit 0 with zero failures.

### Task 3: Apply the home Hermes configuration

**Files:**
- Modify: `/home/birdyo/.hermes/config.yaml` under `model` and `auxiliary.compression`.

**Interfaces:**
- Consumes: the verified online Codex subscription model.
- Produces: an online default plus a local-only compact lane when the active provider is local.

- [ ] **Step 1: Smoke-test the current Codex subscription model**

```bash
hermes chat -q 'Reply with exactly: HERMES_CODEX_OK' --provider openai-codex -m gpt-5.6-luna --quiet
```

Expected: response contains `HERMES_CODEX_OK`, exit 0. If rejected, use the model accepted by the real OAuth endpoint; never route it through localhost.

- [ ] **Step 2: Change only the relevant YAML**

Use the verified model for the main online route and replace the static local compression block with:

```yaml
model:
  default: gpt-5.6-luna
  provider: openai-codex
  # remove model.base_url and model.api_key when they are local-only

auxiliary:
  compression:
    provider: auto
    model: auto
    local_model: coder-compact
    timeout: 600
```

Keep the existing local provider/models and all unrelated auxiliary settings unchanged.

- [ ] **Step 3: Validate config without printing secrets**

```bash
hermes chat --help >/dev/null
sed -n '/^model:/,/^agent:/p; /^  compression:/,/^display:/p' ~/.hermes/config.yaml | sed -E '/(api[_-]?key|token|secret|password)/I s/([:=]).*/\\1 <redacted>/'
```

Expected: online `model.provider`, compression `provider: auto`, `model: auto`, `local_model: coder-compact`, and no local base URL in those blocks.

### Task 4: Final verification

**Files:**
- Verify only: Hermes source/test diff and `/home/birdyo/.hermes/config.yaml`.

- [ ] **Step 1: Run the full focused resolver set**

```bash
/var/home/birdyo/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/agent/test_provider_aware_compression.py tests/agent/test_auxiliary_client.py tests/agent/test_auxiliary_config_bridge.py
```

Expected: exit 0 with zero failures.

- [ ] **Step 2: Verify both routes through real imports**

```bash
/var/home/birdyo/.hermes/hermes-agent/venv/bin/python - <<'PY'
from unittest.mock import patch
import agent.auxiliary_client as ac

def resolve(provider, model):
    with patch.object(ac, "resolve_provider_client", return_value=(object(), model)),          patch.object(ac, "_is_provider_unhealthy", return_value=False),          patch.object(ac, "_get_auxiliary_task_config", return_value={"local_model": "coder-compact"}):
        return ac._resolve_auto({"provider": provider, "model": model}, task="compression")[1]

assert resolve("openai-codex", "gpt-5.6-luna") == "gpt-5.6-luna"
assert resolve("custom:local", "coder-agentic") == "coder-compact"
print("provider-aware compression routes verified")
PY
```

Expected: `provider-aware compression routes verified`.

- [ ] **Step 3: Confirm only intended external files changed**

```bash
git -C /var/home/birdyo/.hermes/hermes-agent diff -- agent/auxiliary_client.py tests/agent/test_provider_aware_compression.py
git -C /var/home/birdyo/.hermes/hermes-agent status --short --branch
```

Expected: only the intended Hermes source/test files are changed; `.install_method` remains untouched. Repository render checks are not applicable because no `modules/` file changed.
