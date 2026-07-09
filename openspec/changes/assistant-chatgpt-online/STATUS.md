# Status — assistant-chatgpt-online (2026-07-10)

## Done (v0 code in tree)

| Area | Location | Evidence |
|---|---|---|
| Modular super-aggregator | `modules/assistant-aggregator/` | `verify.sh` ok; `aipc-assistant` CLI |
| Unified text entry | `aipc-assistant --text` | routes local/online |
| Voice → aggregator | `aipc-voice-once` | calls aggregator, falls back to :4100 |
| Keywords + controller (NPU) | control slot + `resident-small` | self-test + smoke earlier |
| NPU-first local chat | `runtime.yaml` `local_backend.mode: auto` | NPU first, agent fallback |
| Multi-site web engine | `aipc_chatgpt/engine.py` + `sites/` | `sites list` / `sites plan` |
| ChatGPT site pack | `sites/chatgpt.py` | inject / voice / login detect |
| Auth session (no passwords) | `auth login\|export\|import` | storage_state + profile |
| First-run UX | `aipc-assistant setup` | checklist + wizard |
| Config + LLM setup plan | `setup_judge.py` | rules + NPU LLM message |
| OpenSpec change | `openspec/changes/assistant-chatgpt-online/` | `validate --strict` ok |

## Intentionally not done (v1+)

| Item | Why |
|---|---|
| Full online idle/max transcript daemon | needs long-running user service |
| system_audio / project / canvas / gpt packs | registry only; packs stubbed |
| Enable `assistant-chatgpt` by default | still `.disabled` until hardware Voice login QA |
| bootc image bake of Playwright browsers | large; post-install best-effort |
| Always-green NPU live smoke | depends on lemonade up; use `auto` fallback |

## How to run on this machine (dev)

```bash
export AIPC_ASSISTANT_ETC=$PWD/modules/assistant-aggregator/files/etc/aipc/assistant
export AIPC_WEB_SITES_CONFIG=$PWD/modules/assistant-chatgpt/files/etc/aipc/assistant/sites.yaml
export PYTHONPATH=$PWD/modules/assistant-aggregator/files/usr/lib:$PWD/modules/assistant-chatgpt/files/usr/lib

./modules/assistant-aggregator/files/usr/bin/aipc-assistant setup
./modules/assistant-aggregator/files/usr/bin/aipc-assistant --text "你好"
# online (remove .disabled first if needed):
# ./modules/assistant-chatgpt/files/usr/bin/aipc-chatgpt auth login
# ./modules/assistant-aggregator/files/usr/bin/aipc-assistant mode online
```

**v0 is feature-complete in repo for the agreed architecture.** Remaining items are explicit v1 packs / hardware enablement, not missing hub design.
