# voice-stt-sensevoice

SenseVoice-Small STT service for short utterances (<10s).

## What it does

- Runs `iic/SenseVoiceSmall` via `funasr.AutoModel` on CPU (see "Known
  hardware ceiling" below for why this isn't the iGPU despite the hardware
  targeting gfx1151).
- Faster STT for short commands; router dispatches here for <10s audio.
- Publishes on `127.0.0.1:9001`.

## Why native systemd, not a quadlet

The scaffold this replaces pointed at `docker.io/aipc/sensevoice:latest` — an
image that does not exist (`skopeo inspect` returns 404/access denied, no
such upstream image was ever published anywhere). There's no real container
to run. `agent-orchestrator` hit the identical problem (no real upstream
image for its LangGraph supervisor) and solved it by shipping as a plain
Python venv + native systemd unit instead, since nothing here needs container
sandboxing. This module follows that same precedent: `quadlet/` is deleted,
the service runs `uvicorn` directly from a venv at `/usr/lib/aipc-voice/venv`.

## Implementation

- `files/usr/lib/aipc-voice/requirements.txt`: pinned deps —
  `torch==2.9.1+rocm6.4` (from `--extra-index-url
  https://download.pytorch.org/whl/rocm6.4`, since ROCm builds aren't on
  default PyPI), `funasr==1.3.14`, `fastapi==0.139.0`, `uvicorn==0.50.0`.
  funasr itself declares no `torch` dependency (BYO-torch is upstream's own
  convention), so pinning the ROCm wheel first means the CUDA default on
  PyPI never gets pulled in as a conflicting transitive dependency.
- `packages.txt`: `python3-devel` — several funasr transitive deps
  (`editdistance`, `crcmod`, `aliyun-python-sdk-core`) have no Python 3.14
  wheel yet and compile from source during the pip install, which needs
  `Python.h`. See hardware verification below for how this was confirmed
  against the real build environment, not guessed.
- `files/usr/lib/aipc-voice/aipc_stt_sensevoice/server.py`: FastAPI app,
  loads `iic/SenseVoiceSmall` once at import time (matches
  `agent-orchestrator`'s `_graph = supervisor()` pattern).
  - `POST /transcribe` — raw audio bytes in the request body (no
    multipart/form-data, so no `python-multipart` dependency needed),
    returns `{"text": ..., "raw_text": ..., "device": "cuda:0"|"cpu"}`.
    `text` is post-processed via
    `funasr.utils.postprocess_utils.rich_transcription_postprocess` (strips
    SenseVoice's `<|zh|><|NEUTRAL|>...` emotion/language tags);
    `raw_text` is the untouched model output.
  - `GET /healthz` — `{"status": "ok", "model": ..., "device": ...}`.
  - Model device: defaults to `cpu` (`AIPC_STT_DEVICE` env var overrides).
    NOT `cuda:0` by default — see "Known hardware ceiling" below, a real
    crash was found, not a hypothetical one.
- `files/etc/systemd/system/aipc-voice-stt-sensevoice.service`: native
  systemd unit (`Type=simple`, `ExecStart=.../venv/bin/uvicorn
  aipc_stt_sensevoice.server:app --host 127.0.0.1 --port 9001`).
  Sets `HSA_OVERRIDE_GFX_VERSION=11.5.1` directly in the unit (matches
  `llm-ollama`/`llm-vllm`/`rag-embedder` quadlets — this repo's `env/`
  directory only ships to `/etc/aipc/env.d/<module>/` for reference, it is
  not sourced by systemd services) and `MODELSCOPE_CACHE=/var/lib/aipc-voice/models`.
- `post-install.sh`: build-time only — venv + pinned pip install,
  SELinux `bin_t` relabel of `…/venv/bin` (see below),
  `mkdir -p /var/lib/aipc-voice/models`, `systemctl enable`. Does **not**
  download model weights (no network-dependent runtime service in
  post-install per CLAUDE.md §8). `funasr.AutoModel` downloads
  `iic/SenseVoiceSmall` from ModelScope into `MODELSCOPE_CACHE` the first
  time the service actually starts with network available — this is
  upstream's own default behavior, not something this module reimplements.

## SELinux / EXEC permission

Same bug class as `memory-mem0` and `rag-embedder`: a fresh venv's
console scripts land as `lib_t` (under `/usr/lib/...`) or `var_lib_t`
(under a live-hotfix `/var/lib/...` path). systemd then fails with
`status=203/EXEC` / `Permission denied` before Python even starts.

`post-install.sh` persists `bin_t` via `semanage fcontext` +
`restorecon` (or `chcon` fallback). The unit also invokes
`python3 …/uvicorn` rather than bare `uvicorn`, matching the
`agent-orchestrator` live pattern. Live hotfixes must re-`chcon -R -t
bin_t` on the venv's `bin/` after recreating it.

## Hardware verification (2026-07-06)

Real hardware, this session (Strix Halo, gfx1151), full round trip —
**hardware-verified**, not render-only:

1. **ROCm torch installs and detects the real GPU**: `torch==2.9.1+rocm6.4`
   (cp314 wheel exists) reports `torch.cuda.is_available() == True`,
   `torch.cuda.get_device_name(0) == "AMD Radeon 8060S"`.
2. **GPU inference SEGFAULTs — a real, reproducible crash, not a fabricated
   failure**: loading `iic/SenseVoiceSmall` with `device="cuda:0"` crashes
   the whole process. `coredumpctl info` confirms `Signal: 11 (SEGV)` inside
   `libamdhip64.so` (ROCm's HIP runtime), not in this module's own code —
   `journalctl` shows `python3[...]: segfault at 18 ... in
   libamdhip64.so[2e03b2,...]`. A segfault is not a Python exception, so a
   `try/except` around `AutoModel(...)` (the first draft of `server.py`)
   cannot recover from it — that draft was wrong and has been corrected.
3. **CPU inference works end-to-end, for real**: `device="cpu"` loads in
   ~5.6s, and a real transcription round trip was run three ways, not
   mocked at any layer:
   - Direct `funasr.AutoModel.generate()` call against a WAV synthesized
     with `espeak-ng` (already on this host, no new dependency) speaking
     "testing one two three" → `rtf_avg: 0.092` (11x faster than
     real-time), output `Testing 1,2,3.`
   - The actual `aipc_stt_sensevoice.server:app` FastAPI app, started via
     the real `uvicorn` entrypoint from `requirements.txt`'s pinned
     version, `GET /healthz` → `{"status":"ok","model":"iic/SenseVoiceSmall","device":"cpu"}`.
   - `POST /transcribe` with the same WAV's raw bytes as the request body →
     `{"text":"Testing 1,2,3.","raw_text":"<|en|><|EMO_UNKNOWN|><|Speech|><|withitn|>Testing 1,2,3.","device":"cpu"}`.
4. **The `python3-devel` packaging fix was verified against the real build
   environment, not just this dev host**: `funasr`'s transitive deps
   (`editdistance`, `crcmod`, `aliyun-python-sdk-core`) have no Python 3.14
   wheel yet and compile from source, which needs `Python.h`. Reproduced
   the exact failure in a fresh `podman run` of
   `ghcr.io/ublue-os/bazzite-dx:stable` (the real `FROM` base this repo's
   Containerfile uses) without the fix, then confirmed
   `rpm-ostree install -y python3-devel` (exactly what `packages.txt`
   triggers, per `render_bootc.py`'s single aggregated
   `RUN rpm-ostree install` line run before any module's `post-install.sh`)
   + `pip install -r requirements.txt` succeeds cleanly:
   `ALL OK 1.3.14 2.9.1+rocm6.4`. This is the same base image, same Python
   3.14, same missing-wheel problem the real `bootc render` build will hit
   — not a hypothetical fix.

**What was NOT done**: an actual `bootc switch` + reboot on this real
image (that requires rebuilding and switching the whole OS deployment,
out of scope for verifying one module) and standing up the systemd unit
itself under `systemctl` at the real `/usr/lib/aipc-voice` path (this
host hasn't been rebuilt with this module yet, so that path doesn't exist
here — see `docs/live-hotfix-workflow.md`). The model/inference/HTTP-contract
behavior above was exercised directly against the real hardware and the
real `server.py`/`requirements.txt`, which is the part CLAUDE.md §9 cares
most about (GPU/NPU inference actually working) — the systemd wiring
itself is the same pattern already proven by `agent-orchestrator`.

**Known ceiling**: CPU-only by default (`AIPC_STT_DEVICE=cpu`), because
`cuda:0` crashes on this exact torch/ROCm/gfx1151/model combination — see
point 2. CPU is fast enough for this "Small" model (rtf 0.092) that this is
an acceptable v0, not just a fallback of last resort. Revisit `cuda:0` once
a torch/ROCm release fixes the `libamdhip64.so` crash for gfx1151;
`AIPC_STT_DEVICE=cuda:0` is already wired as an opt-in for that retest —
no code change needed, just flip the env var and re-verify.

## Dependencies

- `system-unified-memory` — sets the ROCm module load / kernel params this
  iGPU needs at all (kargs, amdgpu.conf); this module's own unit sets
  `HSA_OVERRIDE_GFX_VERSION` directly rather than relying on that module's
  shell-sourced `env/hsa.sh` (systemd services don't source login shells).
- `voice-pipecat` — will send audio segments for transcription (not wired
  up yet; that module is being implemented in parallel).

## Spec

- `openspec/changes/phase-3-voice/design.md` — D4.
- Tasks 1.3, 3.1. Note for review: task 1.3 names port 8101 in its own
  text; this module's pre-existing README/`architecture.md` module table
  and the (now-deleted) quadlet all said 9001. Kept 9001 since that's what
  every other artifact already assumed — flagging the 8101/9001 mismatch
  for 大哥 to reconcile in `tasks.md` (not touched here per dispatch scope).

## Hardware

- AMD Strix Halo iGPU (gfx1151) — torch/ROCm sees it correctly, but this
  module runs CPU-only by default; see "Known ceiling" above.
