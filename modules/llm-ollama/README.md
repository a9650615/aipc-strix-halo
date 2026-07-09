# llm-ollama

Runs the Ollama daemon as a Podman quadlet, serving local models on the
gfx1151 iGPU via ROCm 7.

## What it does

- Runs `ollama serve` inside a privileged container with `/dev/kfd` and
  `/dev/dri` passed through.
- Exposes an OpenAI-compatible HTTP API on a localhost port.
- Pre-pulls the model weights declared in the module's model manifest.

## Dependencies

- `system-unified-memory` (GTT sizing, HSA overrides).
- `system-base` (Podman, ROCm userspace).

## Consumers

Not called directly by applications. All AI consumers route through
`llm-litellm`, which forwards to Ollama by model name. See `CLAUDE.md §7`.

**Active again (as of 2026-07-07+)** for the giant `qwen35-122b-q3` alias
(`qwen3.5:122b-aipc` optimized tag). Smaller agent models live on Lemonade
Vulkan; 122B stays on Ollama Vulkan because Lemonade's multi-model slot
router crashed with this weight + `max_loaded_models=2`.

### `qwen3.5:122b-aipc` (2026-07-09)

Same Q4_K_M weights as library `qwen3.5:122b` (~81GB), plus:

| Parameter | Value | Why |
|---|---|---|
| `num_ctx` | 65536 | Stock 262k inflates KV on 128GB UMA |
| `temperature` | 0.6 | Coding band |
| `num_predict` | 8192 | Cap runaway agent max_tokens |
| `num_batch` | 512 | Larger micro-batch for prefill |
| LiteLLM `keep_alive` | 15m | Was `0m` → full reload every request |

Hardware smoke 2026-07-09 (Lemonade LLMs unloaded first): cold
load+short chat ~48s wall; warm short chat ~1s wall; `api/ps` shows
`context_length: 65536`.

**Before loading 122B**, unload Lemonade Vulkan LLMs (~20–40GB each) or
the machine only has ~30GB free and thrashing/load failure follows.
One-shot preset switch (preferred):

```sh
aipc models use 122b          # unload Lemonade Vulkan LLMs, warm 122B
aipc models use agent         # unload 122B, warm hermes brain / agent
aipc models use free          # unload heavy models, keep NPU resident-small
aipc models use 122b --no-warm   # unload only (faster return)
aipc models use --list
```

### Temporarily disable 122B (keep closed loop)

When UMA is tight or you only want the voice baseline, **stop Ollama**
(the 122B host) without masking it (masking breaks LiteLLM if the unit
still `Requires=ollama` on older images):

```sh
sudo systemctl stop ollama.service
sudo systemctl disable ollama.service   # no auto-start on boot
# marker (optional): /etc/aipc/models/122b.disabled
```

Re-enable later:

```sh
sudo systemctl enable --now ollama.service
aipc models use 122b
```

Do **not** `systemctl mask ollama` unless you also drop LiteLLM’s hard
`Requires=ollama` (fixed in this module’s sibling `llm-litellm` quadlet:
`Wants`/`After` only).

## Runtime requirements

- `HSA_OVERRIDE_GFX_VERSION=11.5.1` inherited from `system-unified-memory`.
- iGPU visible via `rocm-smi --showid`.

## mlock (pinning large resident models in RAM)

`models.yaml` entries can set `mlock: true` (currently just `main-70b` — the
45GB model whose reload cost actually justifies it). Ollama has no
per-model mlock knob, so this is daemon-wide for whatever's currently
resident, once any manifest entry requests it:

- `post-install.sh` greps the static manifest at build time and writes
  `/etc/aipc/env.d/llm-ollama/mlock.env` with `LLAMA_ARG_MLOCK=1` (or
  empty) — a pure function of a static file, no live service needed, so
  it belongs at build time rather than in `aipc-models-dir-setup`'s
  runtime resolver.
- The quadlet sources that file via `EnvironmentFile=` and grants
  `AddCapability=CAP_IPC_LOCK` — the actual missing piece for `mlock()` to
  succeed at scale (per `mlock(2)`, `CAP_IPC_LOCK` also makes the kernel
  ignore `RLIMIT_MEMLOCK`, so no `Ulimit=` override is needed).
- Hardware-verified 2026-07-04: `EnvironmentFile=` in a quadlet does
  **not** honor systemd's `-` optional-file prefix the way a native unit
  does — it becomes a literal relative path segment and the container
  fails to start. Since `post-install.sh` always creates `mlock.env`, the
  path is just absolute, no `-` prefix.
- Verified end-to-end against a real load (`llama3.2:3b`, mlock env
  present): `CAP_IPC_LOCK` shows in `podman inspect ollama
  --format '{{.EffectiveCaps}}'`, and the spawned `llama-server`'s
  `/proc/<pid>/status` shows a non-zero `VmLck` (0 without the capability).
