# Hermes Dynamic MoA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Hermes platform and inherited subagent an on-demand `consult_models` MCP tool whose first advisor is the existing quota-gated `glm-cloud` model.

**Architecture:** Refactor the existing GLM adapter into a shared advisor call that masks credential-shaped strings, then expose it through a thin local FastMCP stdio server. An idempotent Hermes-config command registers the MCP server, enables its dynamic toolset on every platform, and preserves it for delegated children. Hermes remains the aggregator; advisors never run automatically.

**Tech Stack:** Python 3.11+, stdlib `urllib`, FastMCP from `mcp>=1.28`, `ruamel.yaml` round-trip YAML, Hermes dynamic MCP toolsets, LiteLLM, CodexBar Z.AI quota.

## Global Constraints

- All model inference goes through LiteLLM alias `glm-cloud`; no direct Z.AI calls from Hermes or the MCP server.
- No API key is written to Hermes config, logs, tests, or repository files.
- The MCP receives only its explicit `question`; it never receives transcript, memory, files, or tool results automatically.
- Credential-shaped substrings are masked; broad PII and moderation classifiers are out of scope.
- Unknown/stale/exhausted quota and provider failures return structured fail-soft results.
- The module must render identically to bootc and Ansible targets.
- Build-time scripts must not contact live services or modify a user's home directory.

---

### Task 1: Shared quota-gated advisor core

**Files:**
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/glm_tool.py`
- Modify: `modules/agent-orchestrator/tests/test_glm_tool.py`

**Interfaces:**
- Produces: `mask_credentials(text: str) -> str`
- Produces: `consult_glm(question: str, *, lookup=None, post=None) -> dict[str, Any]`
- Preserves: `ask_glm(prompt, data_scope, interaction, *, lookup=None, post=None)` for Daily Assistant.

- [ ] **Step 1: Write failing masking and shared-advisor tests**

```python
def test_consult_glm_masks_credentials_before_dispatch() -> None:
    sent: list[str] = []
    result = consult_glm(
        "review this code; api_key=1234567890abcdef",
        lookup=fresh_quota,
        post=lambda prompt: sent.append(prompt) or "safe answer",
    )
    assert result == {
        "status": "ok",
        "advisor": "glm",
        "content": "safe answer",
    }
    assert sent == ["review this code; [REDACTED]"]


def test_consult_glm_keeps_unknown_quota_local() -> None:
    called = False

    def post(_: str) -> str:
        nonlocal called
        called = True
        return "unexpected"

    result = consult_glm("review this", lookup=lambda _: {"status": "error"}, post=post)
    assert result["status"] == "local_only"
    assert called is False
```

- [ ] **Step 2: Run the tests and observe the expected failure**

Run: `pytest -q modules/agent-orchestrator/tests/test_glm_tool.py -k 'consult_glm'`

Expected: collection or assertion failure because `consult_glm` does not exist.

- [ ] **Step 3: Implement the minimal shared core**

```python
def mask_credentials(text: str) -> str:
    return _SECRET.sub("[REDACTED]", text)


def consult_glm(
    question: str,
    *,
    lookup: Callable[[str], dict[str, Any]] | None = None,
    post: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    question = question.strip()
    if not question:
        return {"status": "error", "advisor": "glm", "detail": "question is empty"}
    try:
        quota = (lookup or _lookup_zai)("zai")
    except (ImportError, OSError, ValueError) as exc:
        return {"status": "local_only", "advisor": "glm", "detail": str(exc)}
    if not _quota_available(quota):
        return {
            "status": "local_only",
            "advisor": "glm",
            "detail": "Z.AI quota unavailable or exhausted",
        }
    try:
        content = (post or _post_glm)(mask_credentials(question))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"status": "local_only", "advisor": "glm", "detail": str(exc)}
    return {"status": "ok", "advisor": "glm", "content": content}
```

Keep `ask_glm`'s current scope/interaction checks for Daily Assistant, then delegate its successful path to `consult_glm` and translate `advisor` to `tool: "ask_glm"` so its public result remains compatible.

- [ ] **Step 4: Run focused and existing GLM tests**

Run: `pytest -q modules/agent-orchestrator/tests/test_glm_tool.py`

Expected: all tests pass; Daily Assistant's strict legacy behavior remains covered.

- [ ] **Step 5: Commit**

```bash
git add modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/glm_tool.py modules/agent-orchestrator/tests/test_glm_tool.py
git commit -m "refactor(agent): share quota-gated GLM advisor core" \
  -m $'Co-authored-by: Codex GPT-5 <noreply@openai.com>\nAgent-Role: 副官\nAgent-Run: hermes-dynamic-moa-2026-07-12\nSpec-Task: 0002-assistant-intelligence-routing#6.12'
```

### Task 2: Dynamic advisor MCP server

**Files:**
- Create: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/dynamic_moa.py`
- Create: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/dynamic_moa_mcp.py`
- Create: `modules/agent-orchestrator/tests/test_dynamic_moa.py`
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/requirements.txt`

**Interfaces:**
- Consumes: `consult_glm(question: str, *, lookup=None, post=None)` from Task 1.
- Produces: `consult_models(question: str, advisors: list[str] | None = None) -> dict`
- Produces: stdio MCP server named `dynamic-moa` with exactly one tool, `consult_models`.

- [ ] **Step 1: Write failing advisor-selection tests**

```python
def test_default_advisor_is_glm() -> None:
    calls: list[str] = []
    result = consult_models(
        "review this",
        run_glm=lambda question: calls.append(question) or {
            "status": "ok", "advisor": "glm", "content": "answer"
        },
    )
    assert calls == ["review this"]
    assert result == {"status": "ok", "advisors": [{"status": "ok", "advisor": "glm", "content": "answer"}]}


def test_unknown_advisor_fails_without_calling_glm() -> None:
    result = consult_models("review this", ["unknown"], run_glm=lambda _: None)
    assert result == {
        "status": "error",
        "detail": "unknown advisors: unknown",
        "available_advisors": ["glm"],
    }
```

- [ ] **Step 2: Run the test and observe the expected import failure**

Run: `pytest -q modules/agent-orchestrator/tests/test_dynamic_moa.py`

Expected: FAIL because `aipc_agent.dynamic_moa` does not exist.

- [ ] **Step 3: Implement the pure advisor dispatcher**

```python
from collections.abc import Callable
from typing import Any

from aipc_agent.glm_tool import consult_glm


def consult_models(
    question: str,
    advisors: list[str] | None = None,
    *,
    run_glm: Callable[[str], dict[str, Any]] = consult_glm,
) -> dict[str, Any]:
    selected = list(dict.fromkeys(advisors or ["glm"]))
    unknown = [name for name in selected if name != "glm"]
    if unknown:
        return {
            "status": "error",
            "detail": f"unknown advisors: {', '.join(unknown)}",
            "available_advisors": ["glm"],
        }
    results = [run_glm(question) for _ in selected]
    return {
        "status": "ok" if all(r.get("status") == "ok" for r in results) else "partial",
        "advisors": results,
    }
```

- [ ] **Step 4: Add the thin FastMCP entrypoint and dependency**

```python
from mcp.server.fastmcp import FastMCP

from aipc_agent.dynamic_moa import consult_models as _consult_models

mcp = FastMCP("dynamic-moa")


@mcp.tool()
def consult_models(question: str, advisors: list[str] | None = None) -> dict:
    """Ask configured advisor models only when a second opinion is useful.

    Send a focused question plus only necessary code/context. Never include
    credentials. Keep requests likely to trigger provider moderation local.
    """
    return _consult_models(question, advisors)


if __name__ == "__main__":
    mcp.run()
```

Append `mcp>=1.28` to `requirements.txt`; do not add FastMCP separately.

- [ ] **Step 5: Verify dispatcher and MCP registration**

Run:

```bash
pytest -q modules/agent-orchestrator/tests/test_dynamic_moa.py
PYTHONPATH=modules/agent-orchestrator/files/usr/lib/aipc-agent \
  /usr/lib/aipc-agent/venv/bin/python -c \
  'from aipc_agent.dynamic_moa_mcp import mcp; assert mcp.name == "dynamic-moa"'
```

Expected: tests pass. The second command is hardware/runtime-tier and is recorded as unavailable if the installed venv does not yet contain the new dependency.

- [ ] **Step 6: Commit**

```bash
git add modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/dynamic_moa.py modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/dynamic_moa_mcp.py modules/agent-orchestrator/files/usr/lib/aipc-agent/requirements.txt modules/agent-orchestrator/tests/test_dynamic_moa.py
git commit -m "feat(agent): expose dynamic model advisors over MCP" \
  -m $'Co-authored-by: Codex GPT-5 <noreply@openai.com>\nAgent-Role: 副官\nAgent-Run: hermes-dynamic-moa-2026-07-12\nSpec-Task: 0002-assistant-intelligence-routing#6.11,6.14'
```

### Task 3: Idempotent Hermes configuration

**Files:**
- Create: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/hermes_dynamic_moa_config.py`
- Create: `modules/agent-orchestrator/files/usr/bin/aipc-hermes-enable-dynamic-moa`
- Create: `modules/agent-orchestrator/tests/test_hermes_dynamic_moa_config.py`
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/requirements.txt`

**Interfaces:**
- Produces: `configure(config: MutableMapping, *, python: str, pythonpath: str) -> bool`, returning whether data changed.
- Produces: `aipc-hermes-enable-dynamic-moa [CONFIG_PATH]`, defaulting to `$HOME/.hermes/config.yaml`.

- [ ] **Step 1: Write a failing config transformation test**

```python
def test_configure_all_platforms_and_delegation() -> None:
    config = {
        "mcp_servers": {"mem0": {"command": "python", "args": ["mem0"]}},
        "platform_toolsets": {
            "cli": ["hermes-cli"],
            "telegram": ["hermes-telegram"],
        },
        "delegation": {"max_concurrent_children": 3},
    }
    changed = configure(config, python="/venv/python", pythonpath="/usr/lib/aipc-agent")
    assert changed is True
    assert config["mcp_servers"]["dynamic-moa"] == {
        "command": "/venv/python",
        "args": ["-m", "aipc_agent.dynamic_moa_mcp"],
        "env": {"PYTHONPATH": "/usr/lib/aipc-agent"},
        "timeout": 180,
    }
    assert config["platform_toolsets"]["cli"] == ["hermes-cli", "mcp-dynamic-moa"]
    assert config["platform_toolsets"]["telegram"] == ["hermes-telegram", "mcp-dynamic-moa"]
    assert config["delegation"]["inherit_mcp_toolsets"] is True
    assert configure(config, python="/venv/python", pythonpath="/usr/lib/aipc-agent") is False
```

- [ ] **Step 2: Run the test and observe the expected import failure**

Run: `pytest -q modules/agent-orchestrator/tests/test_hermes_dynamic_moa_config.py`

Expected: FAIL because the config module does not exist.

- [ ] **Step 3: Implement the pure mapping update**

```python
def configure(config, *, python: str, pythonpath: str) -> bool:
    before = repr(config)
    config.setdefault("mcp_servers", {})["dynamic-moa"] = {
        "command": python,
        "args": ["-m", "aipc_agent.dynamic_moa_mcp"],
        "env": {"PYTHONPATH": pythonpath},
        "timeout": 180,
    }
    for toolsets in config.setdefault("platform_toolsets", {}).values():
        if "mcp-dynamic-moa" not in toolsets:
            toolsets.append("mcp-dynamic-moa")
    config.setdefault("delegation", {})["inherit_mcp_toolsets"] = True
    return repr(config) != before
```

- [ ] **Step 4: Implement atomic round-trip YAML CLI**

Use `ruamel.yaml` round-trip mode, preserve the original file mode, write to a sibling temporary file, then `os.replace`. Default runtime paths:

```python
DEFAULT_PYTHON = "/usr/lib/aipc-agent/venv/bin/python"
DEFAULT_PYTHONPATH = "/usr/lib/aipc-agent"
```

The `/usr/bin/aipc-hermes-enable-dynamic-moa` wrapper is:

```sh
#!/bin/sh
set -eu
exec /usr/lib/aipc-agent/venv/bin/python -m aipc_agent.hermes_dynamic_moa_config "${1:-$HOME/.hermes/config.yaml}"
```

Append `ruamel.yaml>=0.18` to the module requirements. The command must fail with one line on stderr when the config file is absent; it must never create a new Hermes config from guesses.

- [ ] **Step 5: Test idempotency and comment preservation**

Run: `pytest -q modules/agent-orchestrator/tests/test_hermes_dynamic_moa_config.py`

Expected: tests pass, including two consecutive writes producing byte-identical YAML on the second invocation and preserving a fixture comment.

- [ ] **Step 6: Commit**

```bash
git add modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/hermes_dynamic_moa_config.py modules/agent-orchestrator/files/usr/bin/aipc-hermes-enable-dynamic-moa modules/agent-orchestrator/files/usr/lib/aipc-agent/requirements.txt modules/agent-orchestrator/tests/test_hermes_dynamic_moa_config.py
git commit -m "feat(agent): configure dynamic advisors for all Hermes agents" \
  -m $'Co-authored-by: Codex GPT-5 <noreply@openai.com>\nAgent-Role: 副官\nAgent-Run: hermes-dynamic-moa-2026-07-12\nSpec-Task: 0002-assistant-intelligence-routing#6.13'
```

### Task 4: Module contract, documentation, and render parity

**Files:**
- Modify: `modules/agent-orchestrator/README.md`
- Modify: `modules/agent-orchestrator/verify.sh`
- Modify: `openspec/changes/0002-assistant-intelligence-routing/tasks.md`
- Modify: `docs/agent-log.md`

**Interfaces:**
- Consumes all Task 1–3 public commands and files.
- Produces reproducible operator instructions and verification evidence.

- [ ] **Step 1: Add a failing module contract check**

Extend `verify.sh` with build-safe checks only:

```sh
test -x "$this_dir/files/usr/bin/aipc-hermes-enable-dynamic-moa" || {
    echo "agent-orchestrator: dynamic MoA configurator missing" >&2
    exit 1
}
PYTHONPATH="$this_dir/files/usr/lib/aipc-agent" python3 -m py_compile \
    "$this_dir/files/usr/lib/aipc-agent/aipc_agent/dynamic_moa.py" \
    "$this_dir/files/usr/lib/aipc-agent/aipc_agent/dynamic_moa_mcp.py" \
    "$this_dir/files/usr/lib/aipc-agent/aipc_agent/hermes_dynamic_moa_config.py"
```

Run: `bash modules/agent-orchestrator/verify.sh`

Expected before installation/live service availability: the existing runtime portion may fail because `/usr/lib/aipc-agent/venv` or the service is absent, but the new static contract must execute before that failure.

- [ ] **Step 2: Document enablement and fail-soft behavior**

Add exact operator commands to the README:

```bash
aipc-hermes-enable-dynamic-moa
hermes mcp test dynamic-moa
# Existing session:
/reload-mcp
```

Document that `consult_models` is on-demand, that Hermes is the aggregator, that GLM quota comes from CodexBar, and that no provider key enters Hermes config.

- [ ] **Step 3: Run static tests and linters**

Run:

```bash
pytest -q modules/agent-orchestrator/tests/test_glm_tool.py \
  modules/agent-orchestrator/tests/test_dynamic_moa.py \
  modules/agent-orchestrator/tests/test_hermes_dynamic_moa_config.py
ruff check modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent \
  modules/agent-orchestrator/tests
sh -n modules/agent-orchestrator/files/usr/bin/aipc-hermes-enable-dynamic-moa \
  modules/agent-orchestrator/verify.sh
npx -y @fission-ai/openspec validate 0002-assistant-intelligence-routing --strict
```

Expected: all new/focused tests pass, ruff and shell syntax are clean, OpenSpec is valid.

- [ ] **Step 4: Render both targets and parity-test**

Run:

```bash
PYTHONPATH=tools python -m aipc_lib.cli render bootc \
  --image-ref localhost/aipc:dynamic-moa-verify \
  --build-date 2026-07-12 --out /tmp/aipc-dynamic-moa.Containerfile
PYTHONPATH=tools python -m aipc_lib.cli render ansible \
  --out /tmp/aipc-dynamic-moa.yml
PYTHONPATH=tools pytest -q tools/tests/test_render_bootc.py \
  tools/tests/test_render_ansible.py tools/tests/test_render_parity.py
```

Expected: both renders write output and all render tests pass.

- [ ] **Step 5: Record implementation status**

Mark tasks 6.11–6.15 complete. Leave 6.16 unchecked until the physical machine proves normal-session and delegated-child calls. Append one `docs/agent-log.md` row with exact static/render/hardware tiers and the commit range.

- [ ] **Step 6: Commit**

```bash
git add modules/agent-orchestrator/README.md modules/agent-orchestrator/verify.sh openspec/changes/0002-assistant-intelligence-routing/tasks.md docs/agent-log.md
git commit -m "docs(agent): verify Hermes dynamic model advisors" \
  -m $'Co-authored-by: Codex GPT-5 <noreply@openai.com>\nAgent-Role: 副官\nAgent-Run: hermes-dynamic-moa-2026-07-12\nSpec-Task: 0002-assistant-intelligence-routing#6.15'
```

### Task 5: Physical-machine canary and merge

**Files:**
- Modify after successful canary: `openspec/changes/0002-assistant-intelligence-routing/tasks.md`
- Modify after successful canary: `docs/agent-log.md`

**Interfaces:**
- Consumes: installed module, live LiteLLM, CodexBar `zai`, and Hermes MCP tooling.
- Produces: hardware evidence for task 6.16.

- [ ] **Step 1: Install/configure without exposing secrets**

Run the normal image deployment or documented live-hotfix copy, then as the Hermes user:

```bash
aipc-hermes-enable-dynamic-moa
hermes mcp test dynamic-moa
```

Expected: the MCP server connects and lists exactly `consult_models`. Inspect `~/.hermes/config.yaml` and confirm it contains no Z.AI key.

- [ ] **Step 2: Test a normal Hermes call**

Ask Hermes to use `consult_models` for a harmless code-review question. Expected: tool result contains advisor `glm`, Hermes synthesizes it, and CodexBar `zai` reports a fresh quota snapshot.

- [ ] **Step 3: Test inherited subagent access**

Delegate a child task that explicitly asks the child to call `consult_models`. Expected: child tool list includes `mcp-dynamic-moa`, the call succeeds, and the result returns to the parent.

- [ ] **Step 4: Test fail-soft**

Temporarily point the MCP process at a stub lookup returning stale quota, or stop LiteLLM after capturing service state. Expected: `consult_models` returns `partial` with advisor `local_only`; Hermes continues locally. Restore the service/config immediately and verify health.

- [ ] **Step 5: Record hardware evidence and commit**

Mark task 6.16 complete only if Steps 1–4 pass. Append the exact commands/outcomes to `docs/agent-log.md`, then commit with `Spec-Task: 0002-assistant-intelligence-routing#6.16`.

- [ ] **Step 6: Independent review, merge, and cleanup**

Request correctness/security review, address findings with tests, merge `feat/hermes-dynamic-moa` back to the user's current branch without overwriting unrelated dirty work, rerun focused tests on the merged result, remove the owned worktree, and delete the feature branch.
