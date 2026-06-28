## ADDED Requirements

### Requirement: LiteLLM Gateway Is The Single OpenAI-Compatible Endpoint

The `llm-litellm` module SHALL provide a LiteLLM proxy daemon listening on
`127.0.0.1:4000`. All AI consumers on the host MUST route LLM requests through
this gateway using the OpenAI-compatible API. The gateway's base URL and port
SHALL be declared in `modules/llm-litellm/env/endpoint` and readable at
`/etc/aipc/env.d/llm-litellm/endpoint` at runtime.

#### Scenario: Gateway health endpoint responds

- **WHEN** `llm-litellm.service` is active
- **THEN** `GET http://127.0.0.1:4000/health` returns HTTP 200

#### Scenario: Gateway advertises declared model aliases

- **WHEN** `llm-litellm.service` is active and at least one backend is reachable
- **THEN** `GET http://127.0.0.1:4000/v1/models` returns a JSON body containing
  a `"data"` array with at least one entry matching the declared model namespace

#### Scenario: No direct backend calls from consumers

- **WHEN** any ai-runtime consumer (Pipecat, Continue.dev, Cline, Aider, Goose,
  LangGraph, agent tools) makes an LLM request
- **THEN** the request is sent to `http://127.0.0.1:4000`, never directly to
  `127.0.0.1:11434` (Ollama), `127.0.0.1:8001` (Lemonade), or
  `127.0.0.1:8000` (vLLM)

---

### Requirement: NPU Inference Via Lemonade SDK

The `llm-lemonade` module SHALL run the Lemonade SDK container as a systemd
service. The service SHALL expose an HTTP API on `127.0.0.1:8001`. The service
SHALL start only when `/dev/accel/accel0` is present (XDNA NPU device node).
Lemonade SHALL serve the model aliases `router-*` and `intent-*` as declared
in `models.yaml`, and these aliases SHALL be registered in the LiteLLM gateway
config.

#### Scenario: Lemonade service active on NPU-equipped host

- **WHEN** `/dev/accel/accel0` exists and `lemonade.service` is enabled
- **THEN** `systemctl is-active lemonade.service` exits 0

#### Scenario: Lemonade API responds

- **WHEN** `lemonade.service` is active
- **THEN** `GET http://127.0.0.1:8001/health` (or equivalent) returns HTTP 200

#### Scenario: Lemonade gracefully absent on non-NPU host

- **WHEN** `/dev/accel/accel0` does not exist
- **THEN** `lemonade.service` is left disabled and `verify.sh` for `llm-lemonade`
  exits 0 with a note on stderr that the NPU device was not found (not a failure)

---

### Requirement: iGPU Main Inference Via Ollama With Pinned Resident Model

The `llm-ollama` module SHALL run the `ollama/ollama:rocm` container as a
systemd service on `127.0.0.1:11434`. The container SHALL set
`OLLAMA_KEEP_ALIVE=-1` so the model declared as `main-70b` in `models.yaml`
remains loaded in GTT indefinitely. `HSA_OVERRIDE_GFX_VERSION` SHALL be set to
`11.5.1` to enable gfx1151 inference.

#### Scenario: Ollama service active with iGPU passthrough

- **WHEN** `ollama.service` is enabled
- **THEN** `systemctl is-active ollama.service` exits 0 and the container has
  `/dev/kfd` and `/dev/dri` device access

#### Scenario: main-70b stays loaded after idle

- **WHEN** the `main-70b` model has been served at least once and no subsequent
  request has arrived for more than 10 minutes
- **THEN** `GET http://127.0.0.1:11434/api/tags` still lists the model
  (not evicted due to `OLLAMA_KEEP_ALIVE=-1`)

#### Scenario: Models directory is the BTRFS bind mount

- **WHEN** `ollama.service` starts
- **THEN** the container's `/models` directory is bind-mounted from
  `/var/lib/aipc-models` on the host

---

### Requirement: vLLM Is Lazy-Loaded And Idle-Evicted

The `llm-vllm` module SHALL install `vllm.service` in a disabled state by
default. LiteLLM SHALL start the service only when a request targets one of the
vLLM-registered model names. The service SHALL be stopped by LiteLLM after
10 minutes of zero traffic to that backend, releasing GTT for other consumers.
The `verify.sh` for `llm-vllm` SHALL exit 2 (not 1) when the service is
disabled, and `aipc doctor` SHALL treat exit 2 as OK-optional.

#### Scenario: vLLM disabled by default

- **WHEN** the image is freshly deployed and `aipc init` has not enabled vLLM
- **THEN** `systemctl is-enabled vllm.service` prints `disabled` and
  `verify.sh` exits 2

#### Scenario: vLLM active when enabled and model is registered

- **WHEN** `/etc/aipc/vllm/enabled` exists and `vllm.service` is started
- **THEN** `systemctl is-active vllm.service` exits 0 and
  `GET http://127.0.0.1:8000/health` returns HTTP 200

---

### Requirement: Models Manifest Declares All Gateway Aliases

The `llm-models` module SHALL provide `models.yaml` at
`/etc/aipc/models/models.yaml`. Each entry SHALL declare: a logical alias (the
public model name consumed by AI software), the backend (`lemonade`, `ollama`,
or `vllm`), and an on-disk reference (GGUF path, ONNX model name, or HuggingFace
repo) relative to `/var/lib/aipc-models`. Adding a new logical model to the
system MUST be accomplished solely by adding an entry to `models.yaml` and
restarting the LiteLLM gateway; no other files SHALL need editing.

#### Scenario: All declared aliases appear in the gateway

- **WHEN** `aipc models sync` has completed and `llm-litellm.service` is active
- **THEN** every alias listed in `models.yaml` appears in the `data` array of
  `GET http://127.0.0.1:4000/v1/models`

#### Scenario: aipc models sync pulls missing weights

- **WHEN** `aipc models sync` is run and a model declared in `models.yaml` is
  absent from `/var/lib/aipc-models`
- **THEN** the command downloads the missing weights to `/var/lib/aipc-models`
  and exits 0

#### Scenario: aipc models sync is idempotent

- **WHEN** `aipc models sync` is run and all declared models are already present
- **THEN** the command exits 0 without re-downloading anything

---

### Requirement: ROCm 7 Stack Recognises gfx1151

The `ai-rocm` module SHALL install the ROCm 7+ HIP runtime, `rocm-smi`, and
`amd-smi` into the image layer. After installation, `rocm-smi` SHALL enumerate
at least one GPU with device ID `gfx1151`. The GTT pool reported by `rocm-smi`
or `amd-smi` SHALL be ≥ 90 % of system RAM (≥ 115 GiB on the reference
128 GB machine).

#### Scenario: rocm-smi enumerates gfx1151

- **WHEN** `ai-rocm` is installed and the host kernel has the amdgpu driver
  loaded
- **THEN** `rocm-smi --showproductname` or `amd-smi list` lists a device
  whose GPU architecture matches `gfx1151`

#### Scenario: GTT pool is at least 90 % of system RAM

- **WHEN** the host has booted with the Phase 0 kernel arguments
- **THEN** `rocm-smi --showmeminfo vram` (or `amd-smi metric --mem`) reports
  available VRAM ≥ 115360 MiB

---

### Requirement: amd-xdna Driver And Lemonade Userspace Recognise The NPU

The `ai-xdna` module SHALL ensure the `amd-xdna` kernel module is loaded and
that Lemonade SDK userspace can enumerate the XDNA 2 NPU. Verification SHALL
use `xdna-smi` or `amd-smi` to confirm the NPU device is present. The
`/dev/accel/accel0` device node SHALL exist after module load.

#### Scenario: amd-xdna module loaded

- **WHEN** `ai-xdna` is installed and the host has rebooted
- **THEN** `lsmod | grep amd_xdna` returns a non-empty result

#### Scenario: NPU device node present

- **WHEN** the amd-xdna module is loaded
- **THEN** `/dev/accel/accel0` exists

#### Scenario: xdna-smi enumerates the NPU

- **WHEN** `/dev/accel/accel0` exists and Lemonade userspace is installed
- **THEN** `xdna-smi examine` (or equivalent) lists at least one NPU device

---

### Requirement: Health Check Covers All ai-runtime Modules

`aipc doctor` SHALL execute `verify.sh` for each of the seven ai-runtime modules
and report per-module OK/FAIL/OPTIONAL status. The gateway liveness check SHALL
include a `GET /v1/models` call to `http://127.0.0.1:4000` and assert that the
response `data` array matches the aliases declared in `models.yaml`. `aipc doctor`
SHALL exit 0 only when all non-optional modules report OK.

#### Scenario: All modules OK on a fully-deployed Phase 1 image

- **WHEN** `aipc doctor` runs on a host with all seven ai-runtime modules
  installed and `aipc models sync` has been run
- **THEN** the output table shows OK for `ai-rocm`, `ai-xdna`, `llm-litellm`,
  `llm-lemonade`, `llm-ollama`, `llm-models`; `llm-vllm` shows OPTIONAL
  (disabled); the process exits 0

#### Scenario: Gateway alias mismatch is reported

- **WHEN** a model listed in `models.yaml` is missing from the LiteLLM gateway
  `/v1/models` response
- **THEN** `aipc doctor` prints FAIL for `llm-litellm` with a one-line diagnosis
  naming the missing alias and exits non-zero
