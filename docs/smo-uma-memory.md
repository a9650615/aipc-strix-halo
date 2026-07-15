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

`configure-lemonade.sh` registers id `Qwen3.5-122B-A10B-Uncensored-APEX-Compact` in
`user_models.json` (weights must already exist under `/var/lib/aipc-models/hf`).

## Dry-run evidence (2026-07-16)

| Step | Result |
|------|--------|
| `resident-small` chat | HTTP 200, ~2–11s |
| `coder-agentic` chat | HTTP 200; GPU = Qwen3.6-35B only |
| `coder-122b` chat | HTTP 200; GPU = 122B only (agentic unloaded) |
| Isolation | `PASS ok_one ok_122 ok_no_mid` |

## Anti-casual-load (service thrash guard)

Background services (voice/agent/learn) previously cold-loaded `assistant-gemma`,
`qwythos-9b`, and `ornith-35b` on every chat. That is now blocked:

| Layer | Control |
|-------|---------|
| LiteLLM SMO | `AIPC_SCHED_GPU_ALLOW=coder-agentic,coder-compact,coder-122b` — others → HTTP 403 |
| LiteLLM SMO | `AIPC_SCHED_MIN_GPU_SWITCH_S=30` — rapid multi-model switching → 503 |
| Agent drop-in | `zzzz-smo-memory-guard.conf` — supervisor/classifier/learn → `resident-small` |
| Hermes | `discover_models: false` |

Expand allowlist only deliberately (e.g. temporary `ornith-35b` for research).

## Hermes workhorse stability

Hermes default is `coder-agentic` → LiteLLM `:4000` → Lemonade Vulkan.

| Policy | Value | Evidence |
|--------|-------|----------|
| GPU allowlist includes agentic | yes | Hermes must not 403 |
| `AIPC_SCHED_WORKHORSE=coder-agentic` | never rate-limited | long tool loops |
| `idle_unload_after_s` agentic | **1800** | thrash was multi-model, not warm agentic |
| `MIN_GPU_SWITCH_S` | 5s | allowlist already blocks casual mid models |
| Background chat/classify/learn | `resident-small` NPU | drop-in `zzzz-smo-memory-guard` |

Do **not** set Hermes default to blocked models (assistant-gemma/ornith).

## Load-wait (ready before forward)

SMO now `POST /api/v1/load` and polls health until the target GPU model is
present before returning from `admit`. Evidence: Hermes `coder-compact` raced
to chat before lemond finished auto-load → 500 "No model loaded".

## Switch rate-limit default 0

With GPU allowlist blocking casual mid models, a 5–30s switch delay only
hurt Hermes compact↔agentic. Default `AIPC_SCHED_MIN_GPU_SWITCH_S=0`.

## Imagine Chat product path (2026-07-16)

`Projects/chat_comfyUI` defaults `IMAGINE_LLM_MODEL=ornith-35b` and may set
`IMAGINE_LLM_VISION_MODEL=vlm-qwen2vl`. Those are intentional product loads,
not casual voice/agent warmups. After agent skill-learn/supervisor moved to
NPU `resident-small`, allowlist includes `ornith-35b` and `vlm-qwen2vl` so
Imagine Web stops getting HTTP 403 while still blocking `assistant-gemma` /
`qwythos-9b` casual classifier/chat paths.

## Capacity-first admission (user directive 2026-07-16)

Normal product calls must **not** hard-403. Default `AIPC_SCHED_GPU_ALLOW`
is empty (allow all registered aliases). Gates:

- MemAvailable + headroom / floor + GTT budget + no swap-admit for large
- At most one **large** model (≥12 Gi `size_work_gb`) on GPU
- Up to **2** non-NPU GPU models so a **small** model (qwythos/compact) can
  start while a workhorse is warm, when free capacity allows
- exclusive 122B still alone; lemonade `max_loaded_models=3` (NPU+2 GPU)

Hard allowlist is optional emergency only.
