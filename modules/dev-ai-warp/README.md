# dev-ai-warp

Warp — AI-native terminal emulator (warp.dev), installed from its own repo.

## What it does

- Ships `/etc/yum.repos.d/warpdotdev.repo` as a static file (declarative;
  matches the `ai-rocm` pattern — no build-time `curl`).
- Installs `warp-terminal` from that repo via `rpm-ostree install` in
  `post-install.sh`.

## Configuring Warp's AI agent to use the LiteLLM gateway

**This is a GUI-only step — there is no config file to pre-stage.**
Confirmed against Warp's own docs 2026-07-03: custom OpenAI-compatible
endpoints (their "Bring Your Own Key" feature, free-plan, distinct from
the enterprise-only "BYOLLM" which is Bedrock-only) are configured
entirely through **Settings → AI** inside the running app. There is no
documented on-disk config file, env var, or CLI flag for this.

After first launch, the user must manually:

1. Open Warp → **Settings → AI**.
2. Choose "custom inference endpoint" / add a custom OpenAI-compatible
   provider.
3. Base URL: `http://127.0.0.1:4000/v1` (the LiteLLM gateway — see
   `modules/llm-litellm/env/endpoint`).
4. Model: any alias from the LiteLLM model namespace (CLAUDE.md §7), e.g.
   `coder-agentic` for agentic tool-use, `resident-small` for quick
   low-latency queries.
5. API key: any non-empty placeholder — LiteLLM's local gateway does not
   require one for local backends.

## Dependencies

- `llm-litellm` (gateway at `http://127.0.0.1:4000`) — not build-enforced
  (nothing to stage at build time for this module), but required for the
  manual step above to have somewhere to point at.

## Consumers

End user via terminal. All model calls route through LiteLLM per
CLAUDE.md §7, once the user completes the one-time GUI setup above.
