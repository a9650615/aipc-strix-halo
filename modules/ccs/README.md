# ccs

[CCS](https://github.com/kaitranntt/ccs) — multi-provider profile/runtime
switcher for Claude Code (and Codex/Droid). This module registers an `aipc`
API profile so `ccs aipc` runs Claude Code against this machine's local
models through the LiteLLM gateway, alongside CCS's other Claude-subscription
/ Codex / GLM / OpenRouter profiles.

## Install

```
npm install -g @kaitranntt/ccs
```

Run this directly on the host, **not** wrapped in `distrobox enter node --`.
Two reasons:

1. Unlike `dev-ai-opencode`/`dev-ai-claude-code`, CCS doesn't run standalone
   as an agent — it's a launcher that execs `claude` in the current shell
   and rewrites `~/.claude/settings.json`. It has to live wherever the
   *interactive* `claude` the user actually runs lives, which on this
   machine is the host, not the `node` container.
2. Hardware-verified 2026-07-04: since the `node` container's `sudo` was
   shadowed to forward to the host (see `dev-distrobox-templates`'s "sudo is
   shadowed" section), `distrobox enter node -- sudo npm install -g ...`
   **also** lands the package on the host now, not the container — global
   npm installs via `sudo` are caught by the same bridge as `dnf`. Installing
   directly on the host just matches what actually happens.

Node is on the host via Homebrew/linuxbrew (`/home/linuxbrew/.linuxbrew/bin`,
already on `$PATH` — see `docs/agent-log.md`'s `ponytail-node-hook-fix` run).

## Configuration

CCS's config schema evolves with its own version (`~/.ccs/config.yaml` has a
`version:` migration counter) and auto-recovers/generates itself on first
run — hand-shipping a static config skel risks drifting out of sync with
whatever CCS version is actually installed. Register the profile with CCS's
own command instead, once per account, after install:

```sh
ccs api create aipc --preset ollama \
  --base-url http://127.0.0.1:4000 \
  --api-key aipc-local \
  --model coder-agentic \
  --extra-models main-70b,coder-strong,coder-thinking,ornith-35b,vlm-qwen2vl,resident-small,router-1b \
  --target claude --yes
```

Hardware-verified 2026-07-04: `ccs aipc --print "reply with exactly: pong"`
round-tripped through CCS's local proxy -> LiteLLM -> Ollama (`coder-agentic`
/ gemma4:26b) and printed `pong`.

`ccs api create` has no flag for Claude Code's permission mode, so add it by
hand once, right after the command above — append to the generated
`~/.ccs/aipc.settings.json`:

```json
{
  "env": { "...": "..." },
  "permissions": {
    "defaultMode": "bypassPermissions"
  }
}
```

This profile is local-model-only and never touches the paid Claude
subscription/API (see below), so the usual reason to keep permission prompts
— a mistaken edit costs real tokens/money — doesn't apply here. Hardware-
verified 2026-07-04: `ccs aipc --print "run \`echo bypass-ok\` using the Bash
tool..."` executed the Bash tool with no permission prompt.

Notes on the flags:

- `--base-url http://127.0.0.1:4000` points at LiteLLM (`llm-litellm`),
  **not** Ollama's own port (`11434`) — CCS's `ollama` preset defaults to
  raw Ollama, but CLAUDE.md §7 requires every AI consumer on this machine to
  go through the LiteLLM gateway so routing/cost observability stays
  centralized. LiteLLM exposes the same OpenAI-compatible shape Ollama does,
  so CCS's OpenAI-compatible-upstream auto-detection treats it identically:
  `ccs aipc` starts a local Anthropic<->OpenAI translation proxy and routes
  Claude Code's `/v1/messages` traffic through it to LiteLLM.
- `--api-key aipc-local` is a non-secret placeholder — LiteLLM's
  `config.yaml` has no `general_settings.master_key` set, so it doesn't
  enforce auth on local requests, but the proxy still requires the header
  to be non-empty.
- `--model coder-agentic` (gemma4:26b) is the default for the same reason
  `dev-ai-opencode` picked it: the `qwen2.5-coder` family's streaming
  tool-calls come back as unstructured text through this
  Ollama/LiteLLM/proxy chain (see `dev-ai-opencode`'s README for the full
  repro). `--extra-models` exposes the rest of `llm-models`' registry for
  CCS's `profile:model` request-time selector, e.g. `aipc:main-70b`.

Large local models (`main-70b` especially, cold-loading 45GB) can take
longer than CCS's default proxy timeout to return a first token; if you see
"socket connection was closed unexpectedly", add
`CCS_OPENAI_PROXY_REQUEST_TIMEOUT_MS` to `~/.ccs/aipc.settings.json`'s `env`
block and restart the proxy (`ccs proxy stop aipc && ccs aipc`).

## Dependencies

- `llm-litellm` (gateway at `http://127.0.0.1:4000`).
- `llm-models` (registers the aliases `--model`/`--extra-models`/
  `profile:model` selectors resolve against).
