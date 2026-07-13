# What

Re-point the `ornith-35b` alias, repo-wide, to the uncensored AEON model with
a grafted vision projector, matching the hardware-verified live state.

- `models.yaml`: `ornith-35b` `model_id` becomes
  `Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-Q4_K_M`; `checkpoints.main`
  becomes
  `mrexodia/Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-GGUF:Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-Q4_K_M.gguf`;
  `checkpoints.mmproj` stays the borrowed
  `SC117/Ornith-1.0-35B-MTP-APEX-GGUF:mmproj-F16.gguf`; `label` gains `vision`.
  `recipe_options` (`-np 4 -kvu`, vulkan, ctx 131072) and
  `idle_unload_after_s: 900` are unchanged.
- `litellm/config.yaml`: `ornith-35b` `model` becomes
  `openai/Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-Q4_K_M`. All other
  params (thinking-mode handling, timeouts) unchanged.
- `llm-lemonade/verify.sh`: the "pulled" grep and the `recipe_options` `-np/-kvu`
  key both reference the new AEON model id.
- `llm-lemonade/lemonade-idle-release.py`: the `__main__` self-check fixture's
  `ornith-35b` `model_id` string tracks the new id (test fixture only, no
  runtime behaviour change).

The mmproj is **cross-repo borrowed** (SC117's, not shipped by mrexodia). It is
dimensionally compatible because AEON and APEX share the
`deepreinforce-ai/Ornith-1.0-35B` (Qwen3.5-35B-A3B MoE) base — same `n_embd`.

Non-goals: changing any other alias, changing the mmproj source, re-quantizing,
or promoting embedded-MTP speculative decoding (still rejected for ornith).
