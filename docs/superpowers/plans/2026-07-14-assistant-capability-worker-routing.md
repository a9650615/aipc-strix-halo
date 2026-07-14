# Assistant Capability Worker Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route fulfillment through the authoritative agent router so live news uses the `coder-agentic` tool worker instead of terminating in the NPU chat model.

**Architecture:** Keep aggregator control actions local, but make its default `auto` fulfillment path call agent `:4100`. Extend the existing capability analyzer with a research capability; map ordinary web grounding to Daily Assistant and deep research to Hermes. Both tool lanes use the existing `coder-agentic` model path; `ornith-35b` remains advisor-only.

**Tech Stack:** Python, unittest/pytest, LangGraph router, LiteLLM-backed local workers, YAML module configuration.

## Global Constraints

- All AI model calls continue through LiteLLM; no direct backend endpoint is added.
- Preserve all unrelated uncommitted user changes in the shared worktree.
- No new dependency, module category, or compatibility shim.
- Static checks are necessary; runtime model/tool behavior remains hardware verification only.

---

### Task 1: Add failing routing and aggregator regression tests

**Files:**
- Modify: `modules/agent-orchestrator/tests/test_router.py`

**Interfaces:**
- Consumes: `aipc_agent.router.analyze.analyze`, `plan_authoritative`, and `aipc_assistant.backends.local.chat`.
- Produces: Regression coverage for news capability, worker selection, and `auto` versus strict `npu` fulfillment.

- [ ] **Step 1: Write the failing tests**

Add these behaviors to the existing test classes:

```python
def test_live_news_is_grounded_search(self) -> None:
    from aipc_agent.router.analyze import analyze
    from aipc_agent.router.envelope import build_envelope

    for text in ("找頭條新聞", "搜尋今日新聞"):
        result = analyze(build_envelope(text, source="voice"))
        self.assertIn("web_search", result["required"])
        self.assertIn("grounding", result["required"])
        self.assertEqual(result["freshness"], "live")

def test_news_and_deep_research_use_distinct_workers(self) -> None:
    from aipc_agent.router.decide import plan_authoritative

    self.assertEqual(
        plan_authoritative("找頭條新聞", source="voice")["target"],
        "daily_assistant",
    )
    self.assertEqual(
        plan_authoritative("深入研究今日台灣新聞", source="voice")["target"],
        "hermes",
    )

def test_auto_fulfillment_always_uses_agent(self) -> None:
    from aipc_assistant.backends import local

    with mock.patch.object(
        local, "_load_runtime", return_value={"local_backend": {"mode": "auto"}}
    ), mock.patch.object(local, "_agent_chat", return_value="agent reply") as agent, mock.patch.object(
        local, "_npu_chat", return_value="npu reply"
    ) as npu:
        self.assertEqual(local.chat("你好"), "agent reply")
    agent.assert_called_once()
    npu.assert_not_called()

def test_strict_npu_mode_stays_local(self) -> None:
    from aipc_assistant.backends import local

    with mock.patch.object(
        local, "_load_runtime", return_value={"local_backend": {"mode": "npu"}}
    ), mock.patch.object(local, "_agent_chat") as agent, mock.patch.object(
        local, "_npu_chat", return_value="npu reply"
    ) as npu:
        self.assertEqual(local.chat("你好"), "npu reply")
    npu.assert_called_once()
    agent.assert_not_called()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=modules/agent-orchestrator/files/usr/lib/aipc-agent pytest -q modules/agent-orchestrator/tests/test_router.py
```

Expected: the existing router tests pass, while the new tests fail because
news currently selects `hermes`, deep research has no `research` capability,
and aggregator `auto` still sends ordinary chat to NPU.

### Task 2: Make capability analysis and worker selection authoritative

**Files:**
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/router/analyze.py`
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/router/shadow.py`
- Modify: `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/graphs.py:838-853`

**Interfaces:**
- Consumes: normalized request text from `analyze()` and `SupervisorState.required`.
- Produces: `research` capability for explicit deep/multi-step research; `local-daily` for ordinary live search; Hermes heavy-model execution for `research` plans.

- [ ] **Step 1: Add the minimum analyzer rules**

In `analyze.py`, add a compiled `_RESEARCH_RE` for explicit phrases:

```python
_RESEARCH_RE = re.compile(
    r"(?i)(深入研究|深度研究|详细调研|詳細調研|深度調查|"
    r"deep research|deep dive|multi[- ]step|多步骤|多步驟)"
)
```

Include `头条|頭條|headline(?:s)?|breaking news` in `_LIVE_RE`. In the live/search branch, keep ordinary requests as `['web_search', 'grounding']` with class `L2`, but prepend `research`, append reason `deep_research`, and set class `L3` when `_RESEARCH_RE.search(text)` matches.

- [ ] **Step 2: Map capabilities to workers**

In `shadow.py`, add the exact stage mapping and change ordinary web grounding:

```python
"research": "local-hermes",
"web_search": "local-daily",
"grounding": "local-daily",
```

The `research` capability is first in deep-research requirements, so it wins
the stage selection; ordinary news stays on Daily Assistant and its existing
`coder-agentic` tool binding.

- [ ] **Step 3: Force the configured heavy Hermes model for research**

In the existing `_hermes_node`, preserve the user-owned `force_default`
change and extend its condition:

```python
force_default = explicit_hermes(text_in) or "research" in (state.get("required") or [])
```

This uses the existing Hermes default (documented as `coder-agentic`) and does
not make `ornith-35b` resident or add a new fallback lane.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=modules/agent-orchestrator/files/usr/lib/aipc-agent pytest -q modules/agent-orchestrator/tests/test_router.py
```

Expected: all router tests pass, including the new worker-selection tests.

### Task 3: Remove aggregator's duplicate capability gate

**Files:**
- Modify: `modules/assistant-aggregator/files/usr/lib/aipc_assistant/backends/local.py:113-203`
- Modify: `modules/assistant-aggregator/README.md:14-20`
- Modify: `modules/assistant-aggregator/files/etc/aipc/assistant/runtime.yaml:14-16`

**Interfaces:**
- Consumes: `local_backend.mode` and the existing `_agent_or_raise` / `_npu_or_raise` helpers.
- Produces: `auto` and `agent` fulfillment through agent `:4100`; explicit `npu` mode only through LiteLLM NPU.

- [ ] **Step 1: Delete `_needs_agent_capabilities()`**

Remove the duplicate regex function from `local.py`; no caller should remain.

- [ ] **Step 2: Make the backend mode the only fulfillment switch**

Replace the capability-first block and final mode branches with:

```python
    if mode == "npu":
        return _npu_or_raise()
    return _agent_or_raise()
```

This makes default `auto` deterministic and prevents an agent-down condition
from silently converting a live/tool request into an ungrounded NPU answer.

- [ ] **Step 3: Correct the two user-facing mode comments**

Document that `auto` is agent-first and `npu` is the strict local opt-out in
the README and runtime YAML, while preserving the user's existing model alias
comments in `runtime.yaml`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=modules/agent-orchestrator/files/usr/lib/aipc-agent pytest -q modules/agent-orchestrator/tests/test_router.py
```

Expected: all focused tests pass and no `_needs_agent_capabilities` reference
remains.

### Task 4: Run repository verification and record the handoff

**Files:**
- No new production files.
- Inspect only the touched files and preserve all unrelated worktree changes.

**Interfaces:**
- Consumes: implementation from Tasks 1–3.
- Produces: static and render verification evidence, with hardware verification explicitly unclaimed.

- [ ] **Step 1: Run static checks**

Run the focused router tests, the aggregator package checks if present, and
`openspec validate 0002-assistant-intelligence-routing --strict`.

- [ ] **Step 2: Run both renders**

Run `tools/aipc render bootc` and `tools/aipc render ansible --check` from the
repository root. Report separately if either command is unavailable due to
the local environment.

- [ ] **Step 3: Review the diff**

Run `git diff --check` and inspect only the intended files. Confirm unrelated
user modifications remain present and no secrets were added.

- [ ] **Step 4: Commit the implementation**

Use a commit with these trailers:

```text
Co-authored-by: Codex-GPT-5 <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: assistant-capability-routing-2026-07-14
Spec-Task: 0002-assistant-intelligence-routing#2.1
```
