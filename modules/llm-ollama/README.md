# llm-ollama

Runs the Ollama daemon as a Podman quadlet, serving local models on the
gfx1151 iGPU via ROCm 7.

## What it does

- Runs `ollama serve` inside a privileged container with `/dev/kfd` and
  `/dev/dri` passed through.
- Exposes an OpenAI-compatible HTTP API on a localhost port.
- Pre-pulls the model weights declared in the module's model manifest.

## Dependencies

- `system-unified-memory` (GTT sizing, HSA overrides).
- `system-base` (Podman, ROCm userspace).

## Consumers

Not called directly by applications. All AI consumers route through
`llm-litellm`, which forwards to Ollama by model name. See `CLAUDE.md §7`.

**Currently idle (as of 2026-07-05).** `coder-agentic` and `ornith-35b` — the
last two aliases that used to resolve here — migrated to `llm-lemonade`'s
`llamacpp:vulkan` backend (35-51% faster, hardware-verified; see
`llm-lemonade`'s README). No alias in `models.yaml` currently points at
Ollama. The service stays installed/enabled (not retired) in case a future
alias needs it again; `aipc doctor` will still report it healthy, it just has
nothing to serve.

## Runtime requirements

- `HSA_OVERRIDE_GFX_VERSION=11.5.1` inherited from `system-unified-memory`.
- iGPU visible via `rocm-smi --showid`.

## mlock (pinning large resident models in RAM)

`models.yaml` entries can set `mlock: true` (currently just `main-70b` — the
45GB model whose reload cost actually justifies it). Ollama has no
per-model mlock knob, so this is daemon-wide for whatever's currently
resident, once any manifest entry requests it:

- `post-install.sh` greps the static manifest at build time and writes
  `/etc/aipc/env.d/llm-ollama/mlock.env` with `LLAMA_ARG_MLOCK=1` (or
  empty) — a pure function of a static file, no live service needed, so
  it belongs at build time rather than in `aipc-models-dir-setup`'s
  runtime resolver.
- The quadlet sources that file via `EnvironmentFile=` and grants
  `AddCapability=CAP_IPC_LOCK` — the actual missing piece for `mlock()` to
  succeed at scale (per `mlock(2)`, `CAP_IPC_LOCK` also makes the kernel
  ignore `RLIMIT_MEMLOCK`, so no `Ulimit=` override is needed).
- Hardware-verified 2026-07-04: `EnvironmentFile=` in a quadlet does
  **not** honor systemd's `-` optional-file prefix the way a native unit
  does — it becomes a literal relative path segment and the container
  fails to start. Since `post-install.sh` always creates `mlock.env`, the
  path is just absolute, no `-` prefix.
- Verified end-to-end against a real load (`llama3.2:3b`, mlock env
  present): `CAP_IPC_LOCK` shows in `podman inspect ollama
  --format '{{.EffectiveCaps}}'`, and the spawned `llama-server`'s
  `/proc/<pid>/status` shows a non-zero `VmLck` (0 without the capability).
