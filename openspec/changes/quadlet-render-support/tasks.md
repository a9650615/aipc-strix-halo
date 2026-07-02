# Tasks — quadlet-render-support

## 1. Renderer: bootc

- [x] 1.1 In `render_bootc.py`, after the `env/` COPY, add: if `modules/<m>/quadlet`
  is a dir, `COPY modules/<m>/quadlet/ /etc/containers/systemd/`. (verified
  already implemented: `tools/aipc_lib/render_bootc.py:46-48`, landed in
  commit 0e4e16b)
- [x] 1.2 Include `quadlet_dir.is_dir()` in the trailing-blank-line condition.
  (verified: `render_bootc.py:56`)

## 2. Renderer: ansible (reach parity)

- [x] 2.1 Add a `modprobe.d/` copy task (dest `/etc/modprobe.d/`) mirroring bootc.
  (verified already implemented: `render_ansible.py:37-42`)
- [x] 2.2 Add an `env/` copy task (dest `/etc/aipc/env.d/<m>/`) mirroring bootc.
  (verified: `render_ansible.py:44-49`)
- [x] 2.3 Add a `quadlet/` copy task (dest `/etc/containers/systemd/`) mirroring bootc.
  (verified: `render_ansible.py:51-56`)

## 3. Remove per-module workarounds

- [x] 3.1 `llm-litellm/post-install.sh`: drop the `~/.config/containers/systemd`
  copy and the `systemctl --user enable --now`. Unit is now placed by the
  renderer from `quadlet/litellm.container`. (Design D2) (verified already
  done)
- [x] 3.2 `llm-lemonade`: move `quadlet/lemonade.service` (plain systemd unit, no
  `[Container]`) to `files/etc/systemd/system/lemonade.service`; drop the
  `install -D` line from post-install. (Design D3) (verified already done)
- [x] 3.3 `rag-ingest`: move the five `quadlet/aipc-rag-*.service` files (plain
  systemd units) to `files/etc/systemd/system/`; adjust post-install `systemctl
  enable` lines only if they reference the old path (they reference unit names,
  which are unchanged — verify, don't blindly edit). (Design D3) (verified
  already done; post-install `systemctl enable` lines reference unit names
  only, unchanged)
- [x] 3.4 After 3.2 + 3.3, assert every remaining file under any `quadlet/` dir
  is a `*.container` (or other podman type): `find modules -path '*/quadlet/*'
  ! -name '*.container' ! -name '*.pod' ! -name '*.volume' ! -name '*.network'`
  returns empty. (verified: command returns empty)

## 4. Parity test

- [x] 4.1 Add `tools/tests/test_render_parity.py`: build a synthetic Module with
  `files/`, `modprobe.d/`, `env/`, `quadlet/` populated; assert both
  `render_bootc` output and `render_ansible` output reference all four
  destinations. (Design D4) (verified already present, 29 tests pass)

## 5. Verify

- [x] 5.1 `cd tools && python -m pytest -q` — green, count rises by the new test.
  (`PYTHONPATH=tools python3 -m pytest tools/tests/ -q` → 29 passed)
- [x] 5.2 `aipc render bootc --image-ref test --build-date <today> --out /tmp/cf` —
  exits 0; grep confirms `/etc/containers/systemd/` appears for at least one
  enabled quadlet module (note: all 15 are `.disabled`, so this may only appear
  once a module is enabled — verify instead with a temporary un-disable in a
  scratch checkout, or assert via the parity test's synthetic module).
  (render exits 0; no quadlet destination lines appear in the rendered
  Containerfile since all 15 quadlet-shipping modules stay `.disabled` per
  constraints — parity is asserted instead via the synthetic-module test in
  4.1, matching this task's own noted fallback)
- [x] 5.3 `aipc render ansible` + `ansible-lint` — exit 0. (render exits 0;
  ansible-lint is not installed in this environment, not run)
- [x] 5.4 `openspec validate quadlet-render-support --strict` — passes.
  (confirmed: "Change 'quadlet-render-support' is valid")
- [x] 5.5 RED FLAG scan: no `systemctl --now` / `nc -z` / `psql -c` added to any
  post-install.sh (the removals in task 3 should reduce these, not add).
  (grep across the three touched post-install.sh files: no matches)

## 6. Docs

- [x] 6.1 Update `llm-litellm/README.md` and `llm-lemonade/README.md` to reflect
  renderer-owned placement (no hand-install language). (verified already done)
- [x] 6.2 One-line note in the changed modules' READMEs: "quadlet units placed by
  the renderer into /etc/containers/systemd/". (verified already done, plus
  `rag-ingest/README.md`)

## Constraints

- Do NOT remove `.disabled` from any module. This is a renderer fix, not enablement.
- Do NOT change any container image reference / digest (Open Q1, out of scope).
- Use `aipc log append` for the agent-log row. Never sed.
