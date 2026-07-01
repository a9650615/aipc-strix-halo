# quadlet-render-support

## Why

Both renderers drop module `quadlet/` directories on the floor. `render_bootc.py`
COPYs `files/`, `modprobe.d/`, and `env/` but never `quadlet/`. `render_ansible.py`
is worse — it COPYs only `files/` and runs post-install, dropping `modprobe.d/`,
`env/`, AND `quadlet/`. This already violates the "Dual Rendering" requirement:
the two targets do not reach the same end state.

Fifteen modules ship `quadlet/` (all `.disabled` today): the four `llm-*`, both
`db-*`, `rag-embedder`, `memory-mem0`, `agent-tools-search`, and five `voice-*`.
None of their container units would ever land in the image. Enabling any of them
would fail at boot with no unit generated. This blocks every service module —
i.e. all of Phase 1-5.

Two modules work around the gap by hand-installing their unit inside
`post-install.sh` (`llm-lemonade` via `install`, `llm-litellm` via a `--user`
copy to `~/.config`). These workarounds are inconsistent with each other and
with the 13 modules that just ship a `quadlet/*.container` and expect the
renderer to place it. This change makes the renderer the single placement path
and removes the need for per-module workarounds.

## What Changes

- `render_bootc.py`: COPY each module's `quadlet/` into the podman-quadlet
  system search path `/etc/containers/systemd/`.
- `render_ansible.py`: reach parity with bootc — COPY `modprobe.d/`, `env/`,
  AND `quadlet/`, matching the same destinations the bootc render uses.
- Decide and document the system-vs-user quadlet question (see design.md).
- Remove the two hand-install workarounds now that the renderer owns placement.
- Add a render-parity guard test so the two renderers can't silently diverge on
  which module subdirectories they consume.

No module is enabled by this change. All 15 stay `.disabled`; this only fixes
what happens when they are eventually enabled on hardware.

## Impact

- Affected specs: `system-foundation` (Dual Rendering requirement).
- Affected code: `tools/aipc_lib/render_bootc.py`, `tools/aipc_lib/render_ansible.py`,
  `modules/llm-lemonade/post-install.sh`, `modules/llm-litellm/post-install.sh`,
  and the renderer tests under `tools/tests/`.
- No runtime behaviour change until a service module's `.disabled` is removed
  (hardware-time work, out of scope here).
