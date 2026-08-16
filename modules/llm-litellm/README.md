# llm-litellm

Runs the LiteLLM proxy as a Podman quadlet. Single entry point for every AI
consumer in the system (Continue.dev, Cline, Aider, Goose, voice pipeline,
agent tools, scripts).

## What it does

- Accepts OpenAI-compatible requests on a localhost port.
- Routes by logical model name to Lemonade, Ollama, or vLLM backends.
- Provides observability (request logs, cost tracking) and rate limiting.

## Model namespace (public API surface)

`resident-small`, `coder-agentic`, `ornith-35b`, `assistant-gemma`,
`qwythos-9b`, `vlm-*`, classic cloud aliases (`main-cloud`, `coder-cloud`,
`thinking-cloud`, `gpt4o-cloud`, `gemini-cloud`, `glm-cloud`), plus
CLIProxy-backed bare names for unified Hermes control (`gpt-5.6-sol`,
`gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.4`, `gpt-5.5`, selected `claude-*`).
Those need `CLIPROXY_API_KEY` in `cloud-keys.env` (see that file's comments).
`glm-cloud` is tool-only and quota-gated by CodexBar provider `zai`; it is
never a default or automatic fallback. Consumers (including Hermes) should
call **only** this gateway (`:4000`) — do not dual-route to CLIProxy or
vendor OAuth from the client.
`qwen35-122b-q3` was retired 2026-07-11 (weights deleted; too heavy for
comfortable UMA use; avoid dual-backend giants).

Adding a new logical model = a LiteLLM config entry, nothing else.

## Container image pin

`quadlet/litellm.container` pins `ghcr.io/berriai/litellm` to a digest
(currently v1.89.4 stable). Floating tags like `:main-latest` are forbidden —
the image is rebuilt on every `bootc switch`, so a tag drift would silently
change behaviour across hosts. Re-verified 2026-07-02 via
`docker buildx imagetools inspect ghcr.io/berriai/litellm:v1.89.4` — the
manifest-list digest matches the pinned `sha256:afdc3cc3…` exactly.

To update the pin:

1. Pick a target version on the [GitHub packages page](https://github.com/orgs/berriai/packages/container/litellm/versions).
2. Copy the digest (`sha256:…`) for the chosen version.
3. Replace the `Image=` line in `quadlet/litellm.container`.
4. Re-render both targets and confirm parity (see `AGENTS.md §4`).

## Timeouts

`config.yaml` sets `router_settings.timeout: 600` and
`litellm_settings.request_timeout: 600` — both are per-request ceilings, not
idle-backend eviction. `cooldown_time: 60` / `allowed_fails: 3` only trip on
failures, not idleness.

Confirmed 2026-07-02 against the pinned tag (v1.89.4): LiteLLM's proxy has
**no** native "unload backend after N minutes of zero traffic" key. Checked
both `litellm/types/router.py::RouterConfig` (the full `router_settings:`
schema — `redis_*`, `cache_*`, `client_ttl`, `num_retries`, `timeout`,
`allowed_fails`, `retry_after`, `routing_strategy`, `model_group_alias`, no
idle field) and `litellm/proxy/_types.py` general settings (only a DB
connection idle timeout, unrelated to model backends). LiteLLM is a
stateless HTTP proxy — it has no handle on the vLLM process's lifecycle, so
it structurally cannot evict it.

Idle eviction must be configured on the backend itself: vLLM's
`--timeout-keep-alive` doesn't stop the process either, so the real fix is a
systemd-level idle-shutdown wrapper (timer or `ExecStopPost`) in
`modules/llm-vllm`'s own quadlet — tracked as a gap, not yet implemented.
Lemonade's model unload policy and Ollama's `OLLAMA_KEEP_ALIVE` are the
equivalent knobs for those two backends. See the `# ponytail:` comment next
to `router_settings` in `config.yaml` for the inline pointer.

## Memory scheduler

`etc/aipc/litellm/scheduler_hook.py` is a `litellm_settings.callbacks` pre-call
hook (0012) gating Lemonade GPU admission on a logical budget ledger plus the
host's real `MemAvailable`, evicting eligible LLM victims and, failing that,
admitting via swap rather than holding or OOMing.

0016 adds a step between eviction and swap-admit: if `AIPC_SCHED_COMFY_BASE`
is set and the ComfyUI at that address reports an empty queue, the scheduler
asks it to free its cache (`POST /free`) once per admission before falling
back to swap — cheaper than grinding swap for GTT ComfyUI isn't using right
now. A busy ComfyUI, an unset/unreachable base, or any `/queue`/`/free` error
is skipped silently (degrade open); the 0012 evict → swap → hold path is
unchanged when reclaim doesn't apply. Disabled unless
`AIPC_SCHED_COMFY_BASE` is uncommented in `quadlet/litellm.container`.

Complementary user-side fix, not owned by this repo: launch `~/ComfyUI` with
`--cache-none` so it releases models after each workflow instead of
accumulating a large GTT + CPU-copy footprint. The gateway reclaim above is
the backstop for when it isn't run that way.

## Unit placement

`quadlet/litellm.container` is placed by the bootc/ansible renderer into
`/etc/containers/systemd/`; podman's generator starts `litellm.service` at
boot. `post-install.sh` only stages `config.yaml` + the endpoint file — it no
longer hand-copies the unit or runs `systemctl --user`.

`quadlet/litellm-external.container` is placed the same way and starts
`litellm-external.service` alongside it — see the next section.

## External LAN gateway (ESP32 host) (2026-08-17)

A second, independent litellm process — `litellm-external.service`, port
`4001`, bound `0.0.0.0` (host networking, so it's reachable on every
interface: LAN wifi `192.168.3.x` and the `tailscale0` tailnet IP both
hardware-confirmed reachable; firewalld's `tailscale` zone is `trusted` by
Tailscale's own install, LAN wifi's `FedoraWorkstation` zone already had
`1025-65535/tcp` open, neither needed a firewall change) — added because an
ESP32 needs to reach `resident-small` (now `gemma4-it-e4b-FLM`, pinned NPU
resident, `ctx_size: 32768` — see `llm-models`) directly as its LLM host,
and the internal gateway (`litellm.service`, `127.0.0.1:4000`) is loopback-
only and has **no auth at all** — every `model_list` entry there is
`api_key: none` and no `general_settings.master_key` is set, because every
existing consumer (Hermes, CCS, the 0012 scheduler) calls it unauthenticated
from the same host. Opening that same process to the LAN would have put
every alias — including the cloud ones billed against a real subscription —
behind zero auth for anyone on the network.

Deliberately a **second process with its own minimal config**
(`config-external.yaml`), not the same `litellm.service` reconfigured, for
two independent reasons:

- **Auth must not leak onto the internal path.** The master key lives in its
  own `external-key.env` (`LITELLM_MASTER_KEY`, not in git), read only by
  `litellm-external.service`'s `EnvironmentFile=`. `litellm.service` keeps
  reading only `cloud-keys.env`, which does not carry that key — so it stays
  keyless and every existing internal caller is unaffected. (Tried once:
  appending `LITELLM_MASTER_KEY` to the shared `cloud-keys.env` would have
  put both processes behind auth, breaking every header-less internal
  caller — reverted before restart, never live.)
- **`config-external.yaml` lists only `resident-small`.** The 0012 memory
  scheduler (`scheduler_hook.py`) tracks GPU admission state in-process; a
  second litellm process serving the same GPU-gated aliases
  (`coder-agentic`/`ornith-35b`/`assistant-gemma`/`qwythos-9b`/`coder-122b`)
  would admit requests with no visibility into what the internal process
  already admitted — real double-admission/OOM risk. `resident-small` is
  NPU/FLM, already exempt from that scheduler (see `llm-models`), so it's
  the only alias safe to serve from an uncoordinated second process without
  a real shared-state fix in `scheduler_hook.py` first. The external
  container doesn't mount `scheduler_hook.py` or `models.yaml` at all.

Hardware-verified 2026-08-17: `:4000` unauthenticated (any/no bearer token)
still serves `resident-small`; `:4001` returns `401` with no/wrong key and
`200` with the real one; both `<aipc-lan-ip>:4001` and `<aipc-tailscale-ip>:4001`
(tailscale0) reachable with the key. ESP32 firmware itself cannot join the
tailnet (no practical WireGuard stack for this class of microcontroller) —
the tailscale path is for debugging from off-LAN, not the ESP32's own route.

## Dependencies

- `llm-lemonade` (NPU + iGPU/Vulkan backend for `resident-small`,
  `coder-agentic`, `ornith-35b` — primary local backend as of 2026-07-05;
  also bundles a vLLM/ROCm backend, not currently wired to a registered
  alias — see its README).
- `llm-ollama` (iGPU backend; installed/enabled but currently idle — no
  aliases point to it, see `llm-ollama`'s README).
- `llm-vllm` (superseded by `llm-lemonade`'s vLLM backend, kept `.disabled`).
- `secrets-sops` (API keys for any cloud fallback routes).

## Consumers

Every AI consumer **must** point at the LiteLLM endpoint declared in
`env/endpoint`. Direct calls to Ollama/Lemonade/vLLM are forbidden outside
their own modules. See `CLAUDE.md §7`.
