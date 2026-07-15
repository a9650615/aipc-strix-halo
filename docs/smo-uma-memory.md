# Single Memory Owner (SMO) — UMA memory policy

**Date:** 2026-07-16  
**Trigger:** Multi-model auto-load thrash (122B + mid LLMs): MemAvailable≈0, GTT≈70Gi, swap≈60Gi.

## Rules

1. **NPU resident** (`resident-small` / FLM) may stay pinned.
2. **At most one GPU LLM** at a time (`AIPC_SCHED_MAX_GPU=1`, `max_loaded_models=2`).
3. **`tier: exclusive`** (coder-122b) requires the GPU pool empty of others first.
4. **Admission gates:** weight budget + `MemAvailable ≥ size + headroom` + `MemAvailable ≥ ram_floor` + GTT budget.
5. **No swap-admit** for loads (`AIPC_SCHED_ALLOW_SWAP_ADMIT=0`).
6. **All loads serialize** on one asyncio lock in LiteLLM `scheduler_hook.py`.
7. Clients must hit **LiteLLM :4000**, not Lemonade load APIs.

## Files

| Path | Role |
|------|------|
| `modules/llm-litellm/files/etc/aipc/litellm/scheduler_hook.py` | SMO policy |
| `modules/llm-litellm/quadlet/litellm.container` | env knobs |
| `modules/llm-models/files/etc/aipc/models/models.yaml` | tiers / sizes / ctx |
| `modules/llm-lemonade/.../configure-lemonade.sh` | `max_loaded_models=2` |

## Verify

```bash
python3 /etc/aipc/litellm/scheduler_hook.py --self-test
curl -sS http://127.0.0.1:8001/api/v0/health | jq '{loaded: [.all_models_loaded[]?.model_name], max: .max_models}'
awk '/MemAvailable/{printf "MemAvail=%.1fG\n",$2/1024/1024}' /proc/meminfo
numfmt --to=iec-i < /sys/class/drm/card1/device/mem_info_gtt_used
```

## 122B

Use only via gateway alias `coder-122b`. Work ctx **65536**. Expect unload of agentic/ornith first; if MemAvailable too low → HTTP 503 with SMO detail (not thrash).
