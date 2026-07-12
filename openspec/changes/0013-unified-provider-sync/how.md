# How

## hermes_sync.py (new, mirrors opencode_sync.py)

`tools/aipc_lib/hermes_sync.py`:
- `sync_config(config_path=~/.hermes/config.yaml, base_url=DEFAULT_LITELLM_BASE)`
- Reuses `opencode_sync.fetch_model_ids` + `NON_CHAT_ALIASES` and the
  manifest's `is_cloud` filter (same rules → same resulting alias set).
- Finds the `custom_providers` entry whose `url` targets the LiteLLM base
  (name `local` today); replaces its `models` dict with
  `{alias: {"context_length": 131072}}`, preserving any existing per-alias
  `context_length` override. Other config keys untouched.
- Write path: `yaml.safe_dump(..., sort_keys=False)` to a temp file in the
  same directory, timestamped `.bak` of the original, then `os.replace` —
  Hermes already has `config.yaml.corrupt.*.bak` scars, so no in-place
  truncation. Round-trip drops YAML comments; checked 2026-07-12: the live
  file is machine-managed and comment-free.

## `aipc providers sync` (cli.py)

New `providers` group with `sync`: calls opencode/ccs/hermes syncs in
sequence, each in its own try block — one consumer's missing config or
unreachable LiteLLM shows as `SKIPPED (<reason>)` for that consumer, the rest
still run; exit non-zero only if every consumer failed.

## Auto-run from `aipc models sync`

After `sync_pull` reports at least one successful pull, `models sync` invokes
the same providers-sync routine (best-effort, warns on failure, never fails
the pull). `--no-providers` opts out.

## Not done (deliberate)

- No systemd path-watch unit on models.yaml: the mutation path is
  `aipc models sync` itself, so hooking there covers the real flow without a
  new unit to maintain. Revisit if a second mutation path appears.
- Consumers with true dynamic discovery (none of the three today) need no
  sync; if a future consumer reads `/v1/models` live, it simply isn't added
  here.
