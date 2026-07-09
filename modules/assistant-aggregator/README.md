# assistant-aggregator

Modular **super-aggregator** for aipc assistant turns: one hub between
unified entry (text + voice) and backends (local `:4100`, online ChatGPT
wrapper). See OpenSpec change `assistant-chatgpt-online`.

## Role

- Own `mode` (`local` | `online`), context assembly, control (keywords +
  NPU small-model), allow-listed actions, status.
- Route each `TurnRequest` through a fixed pipeline; feature packs and
  backends register as slots — they do not bypass the hub.

## NPU-first

Default local chat and control use **`resident-small`** (NPU via LiteLLM
`:4000`). You do **not** need ornith-35b / agent `:4100` for basic
assistant turns. Optional: set `runtime.yaml` → `local_backend.mode:
agent` or `auto` when tool-calling Daily Assistant is required.

Online mode still uses the multi-site Chromium engine + subscription
sites; only routing/setup LLMs stay on NPU.

## Pipeline

```text
entry → context → control → actions → backend.local|online → output
```

## Dependencies

- llm-litellm (controller uses `resident-small` when enabled)
- agent-orchestrator (`backend.local` → `http://127.0.0.1:4100/chat`)
- assistant-chatgpt (optional `backend.online`; may be `.disabled`)

## Layout

```text
files/usr/bin/aipc-assistant
files/usr/lib/aipc_assistant/   # Python package
files/etc/aipc/assistant/       # mode, features, keywords, …
```

## First-run UX

```bash
aipc-assistant                  # bare: checklist + hints
aipc-assistant status           # human checklist on TTY
aipc-assistant setup            # local path readiness
aipc-assistant setup --online   # install Chromium if needed + login wizard
aipc-assistant --text "你好"    # local turn when ready
```

Online failures print the same setup hint instead of raw stack noise.
Login collects **session only** (`aipc-chatgpt auth`), never passwords.

## Integration rules

One aggregator, one mode file, one actions allow-list, LiteLLM for local
NLU, degrade without orphaning. Packs that cannot attach to the hub are
out of scope.
