## 1. Existing Modules — Verify And Fix Gaps

- [x] 1.1 `llm-litellm`: quadlet, post-install.sh, verify.sh exist; service
  runs on port 4000; verify.sh checks `/health` and `/v1/models` — shipped.
- [x] 1.2 `llm-litellm`: pin `ghcr.io/berriai/litellm` to a specific digest
  (not `:main-latest`) and document the pin in the module README.
- [~] 1.3 **Redirected, not done.** Investigated 2026-07-02 (see the
  `ponytail:` comment on `config.yaml`'s `router_settings`): LiteLLM
  v1.89.4 has no `idle_timeout`/backend-eviction key at all — it's a
  stateless proxy, it cannot stop the process it routes to. Real fix
  belongs in `llm-vllm`'s own systemd unit (timer or
  `ExecStopPost` idle-shutdown wrapper), not here — and is itself
  blocked on a bigger prerequisite: `llm-vllm/quadlet/vllm.container`
  has a `TODO(unresolved)` saying vLLM has no real HuggingFace-format
  model provisioned yet ("do not enable this service until that's
  resolved"). Not attempted this pass — needs a provisioning decision
  first, not an idle-timer.
- [x] 1.4 `llm-lemonade`: quadlet, post-install.sh, verify.sh exist; service
  runs on port 8001; conditional on `/dev/accel/accel0` — shipped.
- [x] 1.5 `llm-lemonade`: validated against a real running container
  2026-07-04 — the premise was wrong, not just the field names: Lemonade
  Server doesn't consume a mounted `models.yaml` at all (manages models via
  its own CLI). Removed the file; see `llm-lemonade`'s README "Corrected
  assumptions" section for the full list of what else this uncovered
  (port, ROCm env, pull binary name, memlock ulimit).
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
- [~] 2.2 `ai-xdna` scaffolded (README, `modules-load.d` +
  `udev/rules.d` files, verify.sh with the exact 3 checks asked for).
  **`packages.txt`/`post-install.sh` deliberately absent** — the
  module's own README documents why: `amd-xdna-dkms`/`xdna-smi` aren't
  in bazzite-dx's base repos, and closing that gap needs a hardware
  decision (out-of-tree repo file like `ai-rocm`, vs. confirming an
  upstream kmod already ships in-kernel — Linux ≥ 6.10 mainlined
  `amdxdna`, which may make this whole gap moot on this repo's ≥ 6.14
  kernel floor, CLAUDE.md §6). Not re-litigated this pass; this is a
  correct, already-reasoned deferral, not an oversight.
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
- [ ] 3.4 **Not done — needs a design proposal, not a quick renderer.**
  `models.yaml` only carries alias/backend/model_id/size_gb; `config.yaml`
  carries per-alias `litellm_params` overrides (timeout, num_retries,
  api_base) plus extensive hand-written hardware-benchmark comments that
  a naive generated render would destroy. Confirmed the hand-alignment
  risk is real, not theoretical: `embed-bge` drifted out of sync between
  the two files this same session (cut from both 2026-07-04, then
  restored to both by hand 2026-07-06 for phase-2-memory — see that
  change's commit `bf7a370`). Options to weigh next time: extend
  models.yaml's schema to carry litellm_params overrides, vs. a
  base-render + hand-written-override-merge split. Deferred per user
  direction to research established patterns before implementing.

## 4. Extend aipc doctor For ai-runtime

- [x] 4.1 Add `llm-litellm` gateway alias check to `aipc doctor`: call
  `GET http://127.0.0.1:4000/v1/models`, parse `data[].id`, and assert every
  alias in `models.yaml` is present; print FAIL with missing alias name if not.
- [x] 4.2 Confirm `aipc doctor` maps verify.sh exit 2 to OPTIONAL status for
  `llm-vllm` and any other optional module (may already be implemented; check
  and mark done if so).

## 5. Local Build Verification

- [x] 5.1 Confirmed 2026-07-06: `render bootc` includes all 4 currently
  enabled ai-runtime modules (`llm-litellm`, `llm-lemonade`, `llm-ollama`,
  `llm-models`); the other 3 (`ai-rocm`, `ai-xdna`, `llm-vllm`) are
  `.disabled` and correctly excluded, not included-as-disabled — same
  `discover()` behavior confirmed for phase-2-memory.
- [x] 5.2 Run `podman build` of the rendered Containerfile (or CI build) to
  confirm the image builds without error.
- [x] 5.3 Confirmed 2026-07-06: `render ansible` output parses as valid
  YAML. No `--check` flag exists on this CLI.
- [ ] 5.4 **Not run.** Same as phase-2-memory#11.3 — needs a privileged
  container with systemd actually running; out of reach without
  hardware/a real container runtime this session.

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
