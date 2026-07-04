# llm-lemonade

Runs AMD's Lemonade Server — a multi-backend local inference platform, not
just an NPU-only server. On this machine it currently serves one shipped
alias, plus a second capability that's proven but not currently wired to
any registered model:

- **FLM backend (NPU/XDNA)**: `resident-small` — an always-on model that
  has no business permanently occupying iGPU/GTT memory that
  `coder-agentic`/`ornith-35b` also need. The NPU otherwise sits idle.
  Hardware-verified 2026-07-04 with a real chat completion, including
  persistence of the pulled model across a service restart.
- **vLLM backend (ROCm, gfx1151)**: continuous batching + PagedAttention
  for concurrent-request throughput, as opposed to Ollama's single-stream
  serving. Hardware-verified 2026-07-04 with a real chat completion
  against `Qwen3.5-4B-FP16-vLLM` — but **not currently registered as a
  model alias** (the manifest was trimmed 2026-07-04 to a small
  deliberate set; `intent-3b` was cut too, along with the qwen2.5 family
  elsewhere in the manifest). The backend and the fix for its one
  remaining gap (see "`vLLM backend notes`" below) stay documented here
  for whenever a vLLM-backed alias is wanted again.

## Corrected assumptions (2026-07-04)

Earlier scaffolding of this module (pre-hardware-verification) guessed at
several things that turned out wrong once actually tested against a real
running container:

- **No `models.yaml` is consumed by the server.** The previous
  `files/etc/aipc/lemonade/models.yaml` (removed) assumed a static config
  file — Lemonade Server manages models via its own CLI (`pull`/`load`/
  `list`), not a mounted YAML manifest.
- **Default port is `13305`, not `8001`.** The container's own `CMD` is
  `./lemond --host 0.0.0.0` with no `--port` override — the previous
  quadlet's `-p 127.0.0.1:8001:8001` port mapping pointed at a port the
  server wasn't actually listening on internally. Fixed by passing
  `--port 8001` explicitly in the unit's `ExecStart=`.
- **`post-install.sh` conflated build and runtime** (this module's
  `.disabled` reason) — `systemctl enable --now` tried to start the
  container during image build, where no init/services are running.
  Fixed: `enable` only; the unit's own `ConditionPathExists=/dev/accel/accel0`
  correctly gates whether it actually starts, evaluated for real at boot.
- **ROCm backends (`llamacpp:rocm`, `vllm:rocm`) reported "Unsupported
  GPU"** in early testing — not a real hardware limitation. Root cause:
  the container needs `HSA_OVERRIDE_GFX_VERSION=11.5.1` and `/dev/kfd`
  `/dev/dri` passed through, exactly like `llm-ollama` already does
  (gfx1151 isn't in ROCm's officially-listed target list without the
  override). Once added, both flip to `installable`, and `vllm:rocm`
  genuinely serves inference (see below). AMD's own article
  ("Ryzen AI and Radeon are ready to run LLMs Locally with Lemonade
  Software", Nov 2025) lists **ROCm** as the backend for Ryzen AI MAX+ 395
  / Strix Halo specifically — this machine's chip — confirming the fix
  direction, not something contrived.
- **`aipc_lib/models.py`'s pull command used a nonexistent
  `lemonade-server` binary.** The real binaries are `/opt/lemonade/lemonade`
  (CLI client) and `/opt/lemonade/lemond` (server) — fixed.
- **FLM model load failed with "Memlock limits are too low"** under the
  real systemd service, even though the identical `podman run` invocation
  worked fine launched by hand from an interactive shell — hardware-
  verified 2026-07-04 that systemd's restrictive default `LimitMEMLOCK`
  for system units is the difference (an interactive login shell inherits
  a much higher ulimit). Same class of issue as `llm-ollama`'s mlock/
  `CAP_IPC_LOCK` story. Fixed with both `LimitMEMLOCK=infinity` in the
  unit's `[Service]` section and `--ulimit memlock=-1:-1` on the `podman
  run` invocation itself (podman gives containers their own default
  ulimits regardless of the launching process's limits, so both are
  needed, not just one).
- A pulled-but-not-yet-loaded model auto-loads on its first inference
  request, exactly like Ollama — confirmed by pulling a model without an
  explicit `load` and hitting `/api/v1/chat/completions` directly. No
  separate load/pin step is needed in the sync path.

## What it does

- Runs Lemonade Server (`ghcr.io/lemonade-sdk/lemonade-server`) as a plain
  systemd unit (not a quadlet — see "Unit placement" below), with
  `/dev/accel/accel0` (NPU), `/dev/kfd`+`/dev/dri` (ROCm/iGPU), and
  `HSA_OVERRIDE_GFX_VERSION=11.5.1` passed through.
- Persists state across restarts (the container runs `--rm`, so anything
  not explicitly mounted is lost every restart) at three separate host
  paths under `/var/lib/aipc-lemonade/` — hardware-verified 2026-07-04
  that Lemonade's own top-level cache (`/root/.cache/lemonade`: installed
  backends, config) is a **different path** from where FLM actually
  stores pulled model weights (`/root/.config/flm`) and from the
  HuggingFace hub cache llamacpp/vLLM-backend models use
  (`/root/.cache/huggingface`) — mounting only the first one (an earlier
  version of this unit did) silently loses NPU model downloads on every
  container restart while looking like it persisted something:
  - `/var/lib/aipc-lemonade/cache` -> `/root/.cache/lemonade`
  - `/var/lib/aipc-lemonade/flm` -> `/root/.config/flm`
  - `/var/lib/aipc-lemonade/huggingface` -> `/root/.cache/huggingface`
- Exposes an OpenAI-compatible HTTP API on `127.0.0.1:8001`.
- `aipc models sync` pulls `resident-small`'s weights via
  `podman exec lemonade /opt/lemonade/lemonade pull <model-id>` (see
  `llm-models`), same pattern as `llm-ollama`.
- The `vllm:rocm` backend itself is not installed by default — it's a
  ~2.5GB download (`lemonade backends install vllm:rocm` on the running
  container), only relevant if a vLLM-backed alias is registered again.
  The FLM backend (`resident-small`) is bundled and needs no extra install
  step.

## Unit placement

`lemonade.service` is a plain systemd unit (not a podman quadlet), shipped
under `files/etc/systemd/system/` and placed by the renderer.

## Dependencies

- `system-unified-memory` (NPU visible via lspci, amd-xdna driver loaded;
  `HSA_OVERRIDE_GFX_VERSION` for the ROCm backend).
- `system-base` (Podman).
- `llm-models` (registers the aliases that resolve to Lemonade-served
  model ids).

## Consumers

Not called directly. `llm-litellm` routes NPU-eligible models here by
model name (`openai/<lemonade-model-id>` against
`http://127.0.0.1:8001/v1`) — currently just `resident-small`.

## Runtime requirements

- `amd-xdna` driver loaded and NPU visible via `lspci`.
- Lemonade server container image, pinned by digest in
  `files/etc/systemd/system/lemonade.service`:
  `ghcr.io/lemonade-sdk/lemonade-server@sha256:e727643d...` (= tag `v10.8.1`,
  verified against the ghcr manifest 2026-07-02). The previously referenced
  `amd/lemonade-sdk` image does not exist on Docker Hub; upstream publishes to
  ghcr via `lemonade-sdk/lemonade`'s `build-and-push-container.yml`. Bump by
  resolving a newer tag's digest and updating both the unit file and this line.

## Known gap: no NPU/FLM embedding model

Lemonade's registry has no `bge-m3` embedding model (only
`bge-reranker-v2-m3`, a reranker, and alternatives like
`nomic-embed-text-v2-moe`) — noted here in case an embedder alias is
registered again later; not a concern right now since none is registered.

## vLLM backend notes (proven, not currently used by any alias)

- Real HuggingFace-format checkpoints (FP16 safetensors) are available in
  Lemonade's own registry (verified against `Qwen3.5-4B-FP16-vLLM`) —
  Lemonade auto-provisions these, unlike the standalone `llm-vllm` module
  (now superseded, see its README) which had no compatible model
  provisioning path at all.
- The container image is missing a C compiler/libc headers needed for
  Triton's JIT kernel compilation (`vllm:rocm` fails on first model load
  with `stdlib.h file not found` otherwise) — `libc6-dev`+`gcc` need to be
  present. **Not baked into `post-install.sh`** — fixed by hand in a
  throwaway test container only. Doing this in a live `ExecStartPre`
  would need `apt-get install` at every service start, which needs
  network — conflicts with CLAUDE.md §6's offline-once-weights-present
  assumption. The real fix is a custom derived image with these baked
  in, which needs its own build/push pipeline; out of scope until a
  vLLM-backed alias is actually wanted again.
- vLLM's default `--gpu-memory-utilization` (0.92) will fail to start if
  Ollama already has a large model resident (shares the same unified
  memory pool) — pass a lower value via `--vllm-args` if this becomes
  relevant again.
