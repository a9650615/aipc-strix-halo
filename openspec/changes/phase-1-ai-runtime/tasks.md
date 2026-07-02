## 1. Existing Modules — Verify And Fix Gaps

- [x] 1.1 `llm-litellm`: quadlet, post-install.sh, verify.sh exist; service
  runs on port 4000; verify.sh checks `/health` and `/v1/models` — shipped.
- [x] 1.2 `llm-litellm`: pin `ghcr.io/berriai/litellm` to a specific digest
  (not `:main-latest`) and document the pin in the module README.
- [ ] 1.3 `llm-litellm`: add `idle_timeout` (or equivalent) to `config.yaml`
  so vLLM and non-pinned backends are evicted after 10 min of zero traffic;
  confirm the LiteLLM config key against the pinned version.
- [x] 1.4 `llm-lemonade`: quadlet, post-install.sh, verify.sh exist; service
  runs on port 8001; conditional on `/dev/accel/accel0` — shipped.
- [ ] 1.5 `llm-lemonade`: validate `files/etc/aipc/lemonade/models.yaml` field
  names against a running `amd/lemonade-sdk` container; remove the TODO comment
  once confirmed.
- [x] 1.6 `llm-lemonade`: pin `amd/lemonade-sdk` container to a digest;
  document in README.
- [x] 1.7 `llm-ollama`: quadlet, post-install.sh, verify.sh exist; service
  runs on port 11434 with HSA_OVERRIDE_GFX_VERSION — shipped.
- [x] 1.8 `llm-ollama`: add `Environment=OLLAMA_KEEP_ALIVE=-1` to
  `quadlet/ollama.service` so main-70B stays resident (R3 gap — currently
  missing from the shipped quadlet).
- [x] 1.9 `llm-vllm`: quadlet, post-install.sh, verify.sh exist; disabled by
  default; verify.sh exits 2 when disabled — shipped.
- [x] 1.10 `llm-vllm`: confirm that `aipc doctor` treats verify.sh exit 2 as
  OPTIONAL, not FAIL; add handling to the `aipc doctor` runner if not present.

## 2. Add Missing Modules

- [x] 2.1 `ai-rocm`: create `modules/ai-rocm/` with README, packages.txt
  (rocm-smi, amd-smi, rocm-hip-runtime pinned to ROCm 7), post-install.sh
  (idempotent), verify.sh (rocm-smi lists gfx1151 + GTT ≥ 115360 MiB).
- [ ] 2.2 `ai-xdna`: create `modules/ai-xdna/` with README, packages.txt
  (amd-xdna kernel module or DKMS package), post-install.sh (modprobe
  amd_xdna, create /dev/accel/accel0 udev rule if needed), verify.sh
  (`lsmod | grep amd_xdna` + `/dev/accel/accel0` exists + xdna-smi enumerate).
- [x] 2.3 `llm-models`: create `modules/llm-models/` with README, a starter
  `files/etc/aipc/models/models.yaml` that maps at minimum `router-1b`,
  `intent-3b`, `main-70b`, `coder-fast`, `coder-strong`, `coder-thinking`,
  `embed-bge`, `vlm-qwen2vl` to their backends and on-disk references;
  post-install.sh installs the file and runs `aipc models sync --check`;
  verify.sh confirms `/etc/aipc/models/models.yaml` exists and is valid YAML.

## 3. Add aipc models Subcommand

- [x] 3.1 Add `aipc models sync` to `tools/aipc`: reads
  `/etc/aipc/models/models.yaml`, checks each entry against
  `/var/lib/aipc-models`, pulls missing weights via Ollama pull, Lemonade pull,
  or direct download as appropriate for the declared backend.
- [x] 3.2 Add `aipc models list` to show declared aliases, backend, and
  on-disk status (present / missing / size).
- [x] 3.3 Add `aipc models sync --check` (dry-run) that exits non-zero if any
  declared model is missing, without downloading — usable from post-install.sh.
- [ ] 3.4 Render `modules/llm-litellm/files/etc/aipc/litellm/config.yaml` from
  `modules/llm-models/files/etc/aipc/models/models.yaml` at build time
  (renderer-side, not post-install). Single source of truth = the manifest.
  Until done, hand-alignment per Task A must be re-checked when either file
  changes.

## 4. Extend aipc doctor For ai-runtime

- [x] 4.1 Add `llm-litellm` gateway alias check to `aipc doctor`: call
  `GET http://127.0.0.1:4000/v1/models`, parse `data[].id`, and assert every
  alias in `models.yaml` is present; print FAIL with missing alias name if not.
- [x] 4.2 Confirm `aipc doctor` maps verify.sh exit 2 to OPTIONAL status for
  `llm-vllm` and any other optional module (may already be implemented; check
  and mark done if so).

## 5. Local Build Verification

- [ ] 5.1 Run `tools/aipc render bootc`; confirm Containerfile includes all
  seven ai-runtime modules.
- [x] 5.2 Run `podman build` of the rendered Containerfile (or CI build) to
  confirm the image builds without error.
- [ ] 5.3 Run `tools/aipc render ansible --check` and confirm it lints clean.
- [ ] 5.4 Run each module's `verify.sh` in a privileged container against the
  built image; all non-optional modules exit 0.

## 6. AI PC Hardware Verification

- [ ] 6.1 Deploy `:rolling` tag to the AI PC via `bootc switch`.
- [ ] 6.2 Run `aipc doctor` on the AI PC; confirm all seven ai-runtime modules
  report OK or OPTIONAL.
- [ ] 6.3 Smoke-test round-trip: wake-word trigger → STT → `main-70b` via
  LiteLLM gateway → response stream; confirm latency is acceptable.
- [ ] 6.4 Smoke-test NPU path: send a request targeting `router-1b` or
  `intent-3b`; confirm Lemonade handles it (check `lemonade.service` logs).
- [ ] 6.5 Confirm `OLLAMA_KEEP_ALIVE=-1`: wait 15 min with no requests; run
  `GET /api/tags` against Ollama; confirm main-70B is still listed as loaded.

## 7. Archive Change

- [ ] 7.1 Run `npx -y @fission-ai/openspec validate phase-1-ai-runtime` —
  must print `Change 'phase-1-ai-runtime' is valid`.
- [ ] 7.2 Run `npx -y @fission-ai/openspec archive phase-1-ai-runtime` to
  merge the spec into `openspec/specs/ai-runtime/spec.md` and close the change.
