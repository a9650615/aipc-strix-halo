# Tasks for lemonade-compact-idle-unload

- [x] Add `idle_unload_after_s` to `modules/llm-models/files/etc/aipc/models/models.yaml` and set `coder-compact` to `300`.
- [x] Add a Lemonade idle-release timer/service under `modules/llm-lemonade/` that reads the manifest and unloads expired non-pinned models.
- [x] Update `modules/llm-lemonade/README.md` and `modules/llm-models/README.md` to document the compact-only policy and future opt-in path.
- [x] Extend the module verifiers with a policy-field check and expiry-selection self-test.
- [x] Add the compact-idle requirement and scenarios to this change's `ai-runtime` spec delta.
- [x] Run render verification for both targets after implementation.
