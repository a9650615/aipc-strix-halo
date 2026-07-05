# llm-lemonade

Runs AMD's Lemonade Server — a multi-backend local inference platform, not
just an NPU-only server. As of 2026-07-05 it serves **all three** local
model aliases:

- **FLM backend (NPU/XDNA)**: `resident-small` — an always-on model that
  has no business permanently occupying iGPU/GTT memory that
  `coder-agentic`/`ornith-35b` also need. The NPU otherwise sits idle.
  Hardware-verified 2026-07-04 with a real chat completion, including
  persistence of the pulled model across a service restart.
- **llamacpp:vulkan backend**: `coder-agentic` and `ornith-35b` — moved
  here from Ollama 2026-07-05. See "Backend choice: Vulkan, not ROCm"
  below for why, and the speed numbers that justified the move.
- **vLLM backend (ROCm, gfx1151)**: continuous batching + PagedAttention
  for concurrent-request throughput, as opposed to single-stream serving.
  Hardware-verified 2026-07-04 with a real chat completion against
  `Qwen3.5-4B-FP16-vLLM` — but **not currently registered as a model
  alias** (see "`vLLM backend notes`" below for the remaining gap). Stays
  documented here for whenever a vLLM-backed alias is wanted.

## Backend choice: Vulkan, not ROCm (2026-07-05)

`coder-agentic` (Gemma-4-26B-A4B-it-GGUF) and `ornith-35b`
(Ornith-1.0-35B-GGUF-Q4_K_M) were migrated from Ollama to Lemonade's
`llamacpp` backend. AMD's own article ("Ryzen AI and Radeon are ready to
run LLMs Locally with Lemonade Software") names **ROCm** as the
recommended backend for this exact chip (Ryzen AI MAX+ 395 / Strix Halo),
so ROCm was tried first — and rejected, based on real measurements, not
the doc's recommendation:

- **ROCm's allocator can't cross the 4GB VRAM carve-out into GTT by
  default.** Loading either model via `--llamacpp rocm` failed:
  `ggml_backend_cuda_buffer_type_alloc_buffer: allocating ... cudaMalloc
  failed: out of memory` — trying to fit the model into the fixed 4GB
  VRAM pool instead of the ~122GB GTT pool `system-unified-memory`
  provisions (confirmed Ollama was concurrently using ~45GB via GTT with
  no issue at the same time, so this isn't a hardware ceiling). Fixed by
  `lemonade config set enable_dgpu_gtt=true` — after which ROCm *does*
  load successfully.
- **But ROCm+GTT is much slower than Vulkan on this hardware**, measured
  directly: gemma4:26b-equivalent generation speed was **9.4 tok/s on
  ROCm+GTT** vs **38.6-41.6 tok/s on Vulkan** — Vulkan is ~4x faster here.
  Likely explanation: llama.cpp's ROCm/HIP backend expects true
  dedicated VRAM and pays a heavy penalty falling back through GTT on an
  APU, while Vulkan's memory model (via RADV/Mesa) handles the shared
  unified-memory heap natively.
- Full head-to-head vs the previous Ollama setup, same weights, Vulkan
  backend:
  - `coder-agentic` (Gemma-4-26B-A4B-it-GGUF): **41.6 tok/s** (Lemonade
    Vulkan) vs **30.7 tok/s** (Ollama) — **+35%**.
  - `ornith-35b` (Ornith-1.0-35B-GGUF-Q4_K_M): **58.6 tok/s** (Lemonade
    Vulkan) vs **38.8 tok/s** (Ollama) — **+51%**. (Ollama's numbers were
    measured while it was concurrently serving both models at once, which
    if anything favors Ollama in this comparison — contention should only
    make Ollama's numbers worse, not better.)
  - Tool-calling re-verified structured on Vulkan for both models
    (streaming `delta.tool_calls`, `finish_reason: "tool_calls"`) before
    switching — same class of regression risk flagged in
    `dev-ai-opencode`'s README for the qwen2.5 family, checked fresh for
    this new backend rather than assumed safe because "it's still
    llama.cpp underneath."
- `llamacpp.backend: "vulkan"` is pinned in `config.json` (see below) so
  a pulled-but-unloaded model's auto-load-on-first-request picks Vulkan,
  not whatever `"auto"` would otherwise choose.
- `vllm:rocm` (the other backend, see below) is a different code path
  (Python/PyTorch/Triton, not llama.cpp) — this finding is specific to
  llama.cpp GGUF inference on this APU and says nothing about whether
  ROCm is still the right call for vLLM.

### Two settings had to change from Lemonade's defaults

`lemonade.service`'s `ExecStartPre` merges these into `config.json` on
every start (idempotent, skips if the file doesn't exist yet — see the
unit file for why):

- `max_loaded_models: 2` (default `1`) — the default only allows one
  `llamacpp`-backend model resident at a time; loading a second one
  evicts the first (confirmed: loading `ornith-35b` after `coder-agentic`
  was already loaded silently swapped it out, ~20s reload cost on the
  next `coder-agentic` request). `resident-small` doesn't count against
  this limit (different backend/type: `flm`/`npu`). `2` lets both
  `coder-agentic` and `ornith-35b` stay resident simultaneously, matching
  what Ollama did before the migration.
- `enable_dgpu_gtt: true` (default `false`) — see above; without this,
  ROCm can't load either model at all. Left on even though Vulkan is the
  active backend, in case ROCm is revisited later.

## Concurrency: `-np 2 -kvu`, not `-np N` alone (2026-07-05)

`llama-server` has continuous batching on by default (`-cb`), but that
alone didn't help here: Lemonade loads models with `-np` (`--parallel`,
server slot count) left at `auto`, which under `--ctx-size 262144`
(these models' max) resolves to exactly **1 slot** — every request
serializes behind whichever one got there first. Hardware-verified
2026-07-05: a single abandoned 36.8k-token request (Claude Code's own
system prompt, via CCS) occupied that one slot for minutes; every other
request, including plain `/health` and `/slots` checks, queued behind it
with no visible feedback.

Fix is `lemonade load <model> --llamacpp vulkan --ctx-size 262144
--llamacpp-args "-np 2 -kvu" --save-options` — two things together, not
either alone:

- `-np 2` gives 2 server slots instead of 1 (real concurrent requests).
- `-kvu` (`--kv-unified`) is required alongside an explicit `-np` —
  llama-server's help says kv-unified "default: enabled if number of
  slots is auto", meaning setting `-np` explicitly without `-kvu` flips
  it off and the KV buffer gets **statically divided** by slot count
  instead (confirmed: `-np 4` alone reports `n_ctx: 65536` per slot for a
  262144 total — a quarter each, hard-capped). That first attempt broke
  real usage: Claude Code's system prompt (36.8k-56k tokens observed)
  exceeded a 16k-65k per-slot cap and every `coder-agentic`/`ornith-35b`
  request 400'd with `context_length_exceeded`. `-kvu` makes it one
  shared pool sized to the full `--ctx-size` instead of a static split —
  confirmed via `/slots`: both slots report `n_ctx: 262144` (the full
  budget, not divided), and 2 concurrent requests both complete in
  parallel (verified: two simultaneous ornith-35b requests finished in
  6.7s total, not ~2x a single request's time).
- Went with `-np 2` rather than `-np 4`: more slots means a smaller
  effective *combined* budget before contention (unified KV is shared,
  not infinite) — 2 was picked as a reasonable balance for this
  hardware's actual concurrent-user count (one interactive person),
  not a hard ceiling. Revisit if real multi-session contention shows up.
- `--save-options` persists this into `recipe_options.json` under
  `/root/.cache/lemonade` (the mounted `cache` volume, so it survives
  container restarts on an already-provisioned machine) — but this is a
  runtime action requiring the container to already be running, so like
  the model pulls above it's **not** automated in `post-install.sh`; it's
  a one-time manual/CLI step, same category as `aipc models sync`.
  Re-run it (per model) if `recipe_options.json` is ever wiped or on a
  fresh machine before relying on this.

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
- `aipc models sync` pulls all three aliases' weights via
  `podman exec lemonade /opt/lemonade/lemonade pull <model-id>` (see
  `llm-models`), same pattern as `llm-ollama`.
- The `llamacpp:vulkan` backend itself is not installed by default —
  `podman exec lemonade /opt/lemonade/lemonade backends install
  llamacpp:vulkan` (~220MB, one-time). `lemonade load` auto-installs it on
  first use too, but that means the first real chat request eats the
  download — `verify.sh` checks the binary is already present so this
  isn't a surprise in production. The FLM backend (`resident-small`) is
  bundled and needs no extra install step.
- The `vllm:rocm` backend itself is not installed by default either —
  it's a ~2.5GB download (`lemonade backends install vllm:rocm` on the
  running container), only relevant if a vLLM-backed alias is registered
  again.

## Unit placement

`lemonade.service` is a plain systemd unit (not a podman quadlet), shipped
under `files/etc/systemd/system/` and placed by the renderer.

## Dependencies

- `system-unified-memory` (NPU visible via lspci, amd-xdna driver loaded;
  `HSA_OVERRIDE_GFX_VERSION` for the ROCm backend).
- `system-base` (Podman).
- `llm-models` (registers the aliases that resolve to Lemonade-served
  model ids).

## Interaction with system-memory-oom-guard

That module (currently `.disabled`, pending its own threshold-calibration
hardware-verified claim) already knows how to relieve pressure on Lemonade
via `POST /api/v0/unload`. Moving `coder-agentic`/`ornith-35b` here means
this container can now have up to 3 models resident at once
(`resident-small` + 2 via `max_loaded_models`) instead of 1 — worth a
re-check of that module's assumptions before it's ever enabled, not
addressed as part of this change.

## Consumers

Not called directly. `llm-litellm` routes all three local aliases here by
model name (`openai/<lemonade-model-id>` against
`http://127.0.0.1:8001/v1`) — `lemond` (the router on :8001) forwards each
request to whichever child `llama-server` process currently has that
model loaded, spawning/swapping as needed. `llm-ollama` currently has no
aliases pointing to it — it's still installed and enabled, just idle,
since retiring the module entirely wasn't part of this change.

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
  something else already has a large model resident (shares the same
  unified memory pool) — `coder-agentic`/`ornith-35b` moving to this same
  container's `llamacpp:vulkan` backend (see above) makes this more
  likely to matter, not less. Pass a lower value via `--vllm-args` if
  this becomes relevant again.
