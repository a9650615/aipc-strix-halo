## Context

The LiteLLM gateway at `http://127.0.0.1:4000` is the single LLM endpoint (CLAUDE.md §7). All consumers address models by alias name (`main-70b`, `coder-strong`, etc.). Adding cloud models means registering new aliases that route to external providers instead of local backends. The gateway already supports `anthropic/`, `openai/`, and `google/` provider prefixes natively.

## Goals / Non-Goals

**Goals:**

- Five cloud aliases available through the existing LiteLLM gateway.
- API keys encrypted at rest via SOPS, decrypted only at service start.
- Manual switching: the user (or consumer config) picks `main-cloud` instead of `main-70b`.
- Cloud keys optional: if no keys are provisioned, cloud aliases fail gracefully and local models work normally.

**Non-Goals:**

- Auto-fallback on local error — explicit design decision to keep routing predictable.
- Cloud spend management — out of scope for this change.
- Streaming proxy or response caching — LiteLLM defaults are sufficient.

## Decisions

**D1 — Cloud aliases use `-cloud` suffix, not provider-specific names**

*Chosen:* `main-cloud`, `coder-cloud`, `thinking-cloud`, `gpt4o-cloud`, `gemini-cloud`.

*Alternatives:*
- `main-anthropic`, `main-openai`, `main-google`: more explicit but clutters the namespace with provider names consumers shouldn't need to know.
- Same alias, auto-route: breaks the manual-switching constraint; a consumer asking for `main-70b` must always get the local model.

*Why chosen:* The `-cloud` suffix signals "this goes off-machine" without locking the consumer to a provider. The mapping can change (swap Anthropic for another provider) without renaming the alias.

**D2 — Single SOPS file for all cloud keys**

*Chosen:* `secrets/cloud-llm.yaml` with three keys: `anthropic_api_key`, `openai_api_key`, `gemini_api_key`.

*Alternatives:*
- One secret file per provider (`secrets/anthropic.yaml`, etc.): more files to manage, more SOPS invocations, no benefit since all three are needed by the same service.
- Baked into the image: violates CLAUDE.md §5 (never bake secrets).

*Why chosen:* One file, one decryption step, one `EnvironmentFile` directive. All keys go to the same consumer (the LiteLLM container).

**D3 — EnvironmentFile over direct env injection**

*Chosen:* `/etc/aipc/env.d/llm-litellm/cloud-keys.env` loaded via `EnvironmentFile=` in the quadlet.

*Alternatives:*
- `Exec=/bin/sh -c 'source ... && litellm ...'`: fragile, no restart on key change, shell quoting hell.
- `--env ANTHROPIC_API_KEY=...` in quadlet: works but keys would appear in `podman inspect` output.

*Why chosen:* `EnvironmentFile` is the standard Podman/systemd pattern. The `.env` file is `0600 root:root`, not world-readable. Keys appear as container env vars, which is unavoidable — LiteLLM reads them from `os.environ`.

**D4 — LiteLLM `api_key: os.environ/VAR` pattern**

*Chosen:* Each cloud model entry in `config.yaml` uses `api_key: os.environ/ANTHROPIC_API_KEY` (or the equivalent for OpenAI/Google).

*Alternatives:*
- Hardcoded keys in config: violates CLAUDE.md §5.
- LiteLLM master key + per-model key map: overengineered for three providers.

*Why chosen:* LiteLLM natively supports the `os.environ/VAR` syntax. No custom key-management logic needed.

## Secrets Flow

```
secrets/cloud-llm.yaml (SOPS encrypted, committed)
  |
  v  post-install.sh decrypts with /etc/aipc/age.key
/etc/aipc/env.d/llm-litellm/cloud-keys.env (plaintext, 0600 root:root)
  |
  v  EnvironmentFile in quadlet
litellm container env vars:
  ANTHROPIC_API_KEY=sk-ant-...
  OPENAI_API_KEY=sk-...
  GEMINI_API_KEY=AI...
  |
  v  api_key: os.environ/ANTHROPIC_API_KEY in config.yaml
LiteLLM routes to provider APIs
```

## Model Mappings

| Alias | Provider | LiteLLM Model ID | Env Var |
|-------|----------|-------------------|---------|
| main-cloud | Anthropic | anthropic/claude-sonnet-4-6 | ANTHROPIC_API_KEY |
| coder-cloud | Anthropic | anthropic/claude-sonnet-4-6 | ANTHROPIC_API_KEY |
| thinking-cloud | Anthropic | anthropic/claude-opus-4-8 | ANTHROPIC_API_KEY |
| gpt4o-cloud | OpenAI | openai/gpt-4o | OPENAI_API_KEY |
| gemini-cloud | Google | gemini/gemini-2.5-pro | GEMINI_API_KEY |

## Risks / Trade-offs

- **API key exposure in container env**: keys appear in `podman inspect litellm --format '{{.Config.Env}}'`. **Mitigation**: the AI PC is single-user; `podman inspect` requires root or podman group membership. Acceptable for a personal machine.
- **Cloud provider outage**: if Anthropic is down, `main-cloud` fails. **Mitigation**: this is the user's problem — they chose to switch manually. Local models are unaffected.
- **Cost surprise**: unchecked cloud API usage can produce large bills. **Mitigation**: non-goal — document in secrets-setup.md that users should set spend limits at their cloud provider.
- **Key rotation**: rotating a cloud key requires re-encrypting `cloud-llm.yaml` and restarting `litellm.service`. **Mitigation**: standard SOPS workflow, no special handling needed.

## Migration Plan

No migration. Cloud aliases are additive. Existing local-only workflows are unaffected. If `secrets/cloud-llm.yaml` does not exist on a system, the post-install script skips `.env` generation and cloud aliases return a clear error from LiteLLM (missing API key).

## Open Questions

None.
