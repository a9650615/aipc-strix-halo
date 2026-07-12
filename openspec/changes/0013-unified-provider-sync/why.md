# Why: Every Model Swap Requires Hand-Editing N Consumer Configs

models.yaml is the declared single source of truth (CLAUDE.md §7), and LiteLLM
`/v1/models` already exposes the live alias list — but the consumers each keep
their own static copy that only an agent session (or the user) remembers to
update:

- OpenCode `~/.config/opencode/config.json` — has `aipc opencode sync`
- CCS `~/.ccs/aipc.settings.json` (`ANTHROPIC_EXTRA_MODELS`) — has
  `aipc ccs sync`
- Hermes `~/.hermes/config.yaml` `custom_providers[].models` — **no sync at
  all**, hand-edited every time

Observed 2026-07-12 while swapping `ornith-35b` and adding `coder-122b`: the
swap touched models.yaml + litellm config, and then every consumer list was
stale again. The user's requirement: adding/swapping a model must not depend
on an agent remembering which configs to touch — one automated flow, or
dynamic fetch where the consumer supports it.

The two existing syncs prove the pattern (fetch `/v1/models`, rewrite the
static dict); what's missing is Hermes coverage and a single entry point that
runs automatically when the model set changes.
