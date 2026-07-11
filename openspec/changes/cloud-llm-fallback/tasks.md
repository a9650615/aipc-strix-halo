## 1. Secrets Template

- [ ] 1.1 Create `secrets/cloud-llm.yaml.example` with plaintext template:
  ```yaml
  # Cloud LLM API keys — encrypt with sops before committing.
  # See docs/secrets-setup.md for instructions.
   anthropic_api_key: sk-ant-REPLACE_ME
   openai_api_key: sk-REPLACE_ME
   gemini_api_key: AI-REPLACE_ME
   zai_api_key: REPLACE_ME
  ```
- [ ] 1.2 Add `secrets/cloud-llm.yaml.example` to `.gitignore` exception (if secrets dir is gitignored, adjust).

## 2. LiteLLM Config — Cloud Routes

 - [ ] 2.1 Add six cloud model entries to `modules/llm-litellm/files/etc/aipc/litellm/config.yaml`:
  - `main-cloud` → `anthropic/claude-sonnet-4-20250514`, `api_key: os.environ/ANTHROPIC_API_KEY`
  - `coder-cloud` → `anthropic/claude-sonnet-4-20250514`, `api_key: os.environ/ANTHROPIC_API_KEY`
  - `thinking-cloud` → `anthropic/claude-opus-4-20250514`, `api_key: os.environ/ANTHROPIC_API_KEY`
  - `gpt4o-cloud` → `openai/gpt-4o`, `api_key: os.environ/OPENAI_API_KEY`
   - `gemini-cloud` → `gemini/gemini-2.5-pro`, `api_key: os.environ/GEMINI_API_KEY`
   - `glm-cloud` → OpenAI-compatible Z.AI general API, `api_key: os.environ/ZAI_API_KEY`

## 3. Models Manifest — Cloud Aliases

 - [ ] 3.1 Add six entries to `modules/llm-models/files/etc/aipc/models/models.yaml`:
  ```yaml
  - alias: main-cloud
    backend: cloud
    model_id: anthropic/claude-sonnet-4-20250514
    size_gb: 0

  - alias: coder-cloud
    backend: cloud
    model_id: anthropic/claude-sonnet-4-20250514
    size_gb: 0

  - alias: thinking-cloud
    backend: cloud
    model_id: anthropic/claude-opus-4-20250514
    size_gb: 0

  - alias: gpt4o-cloud
    backend: cloud
    model_id: openai/gpt-4o
    size_gb: 0

   - alias: gemini-cloud
     backend: cloud
     model_id: gemini/gemini-2.5-pro
     size_gb: 0

   - alias: glm-cloud
     backend: cloud
     model_id: glm-5.1
     size_gb: 0
  ```
  `size_gb: 0` — no local weights to manage.

## 4. Secrets Post-Install — Cloud Keys Env Generation

- [ ] 4.1 Update `modules/secrets-sops/post-install.sh` to:
  - Check if `/etc/aipc/secrets/cloud-llm.yaml` exists (the encrypted file).
  - If yes: decrypt with `sops-env` pattern, write `/etc/aipc/env.d/llm-litellm/cloud-keys.env` with:
    ```
    ANTHROPIC_API_KEY=<decrypted anthropic_api_key>
    OPENAI_API_KEY=<decrypted openai_api_key>
    GEMINI_API_KEY=<decrypted gemini_api_key>
    ZAI_API_KEY=<decrypted zai_api_key>
    ```
  - Set permissions: `0600 root:root` on the `.env` file.
  - If no: skip with a diagnostic message (cloud aliases will not work).
  - Idempotent: re-running overwrites the `.env` file.
- [ ] 4.2 Ensure `/etc/aipc/env.d/llm-litellm/` directory is created if absent (`mkdir -p`).

## 5. LiteLLM Quadlet — EnvironmentFile

- [ ] 5.1 Add to `modules/llm-litellm/quadlet/litellm.service` under `[Container]`:
  ```ini
  EnvironmentFile=/etc/aipc/env.d/llm-litellm/cloud-keys.env
  ```
  Podman quadlet passes `EnvironmentFile` through to the container as env vars.
- [ ] 5.2 Verify: if the `.env` file is absent, Podman ignores a missing `EnvironmentFile` (or set `EnvironmentFile=-/etc/...` with the `-` prefix to make it explicitly optional).

## 6. Documentation

- [ ] 6.1 Add a "Cloud LLM API Keys" section to `docs/secrets-setup.md`:
  - Copy `secrets/cloud-llm.yaml.example` to `secrets/cloud-llm.yaml`.
  - Replace placeholder values with real API keys.
  - Encrypt: `SOPS_AGE_KEY_FILE=~/.config/aipc/age.key sops --encrypt --in-place secrets/cloud-llm.yaml`.
  - Deploy: the post-install script handles the rest.
  - Note: set spend limits at your cloud provider before enabling.

## 7. Verification

- [ ] 7.1 Run `tools/aipc render bootc`; confirm Containerfile includes updated modules.
- [ ] 7.2 Run `tools/aipc render ansible --check`; confirm lint clean.
- [ ] 7.3 On hardware: encrypt a real `cloud-llm.yaml`, deploy, confirm `litellm.service` starts with cloud env vars loaded.
 - [ ] 7.4 Smoke-test: `curl http://127.0.0.1:4000/v1/chat/completions -d '{"model":"glm-cloud","messages":[...]}'` — confirm response from Z.AI.
- [ ] 7.5 Confirm local models still work when `cloud-llm.yaml` is absent (no `.env` file, no cloud routes active).

## 8. Archive Change

- [ ] 8.1 Run `npx -y @fission-ai/openspec validate cloud-llm-fallback` — must print valid.
- [ ] 8.2 Run `npx -y @fission-ai/openspec archive cloud-llm-fallback` to merge into `openspec/specs/ai-runtime/spec.md`.
