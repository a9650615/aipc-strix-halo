# Tasks — quadlet-render-support

## 1. Renderer: bootc

- [ ] 1.1 In `render_bootc.py`, after the `env/` COPY, add: if `modules/<m>/quadlet`
  is a dir, `COPY modules/<m>/quadlet/ /etc/containers/systemd/`.
- [ ] 1.2 Include `quadlet_dir.is_dir()` in the trailing-blank-line condition.

## 2. Renderer: ansible (reach parity)

- [ ] 2.1 Add a `modprobe.d/` copy task (dest `/etc/modprobe.d/`) mirroring bootc.
- [ ] 2.2 Add an `env/` copy task (dest `/etc/aipc/env.d/<m>/`) mirroring bootc.
- [ ] 2.3 Add a `quadlet/` copy task (dest `/etc/containers/systemd/`) mirroring bootc.

## 3. Remove per-module workarounds

- [ ] 3.1 `llm-litellm/post-install.sh`: drop the `~/.config/containers/systemd`
  copy and the `systemctl --user enable --now`. Unit is now placed by the
  renderer from `quadlet/litellm.container`. (Design D2)
- [ ] 3.2 `llm-lemonade`: move `quadlet/lemonade.service` (plain systemd unit, no
  `[Container]`) to `files/etc/systemd/system/lemonade.service`; drop the
  `install -D` line from post-install. (Design D3)
- [ ] 3.3 `rag-ingest`: move the five `quadlet/aipc-rag-*.service` files (plain
  systemd units) to `files/etc/systemd/system/`; adjust post-install `systemctl
  enable` lines only if they reference the old path (they reference unit names,
  which are unchanged — verify, don't blindly edit). (Design D3)
- [ ] 3.4 After 3.2 + 3.3, assert every remaining file under any `quadlet/` dir
  is a `*.container` (or other podman type): `find modules -path '*/quadlet/*'
  ! -name '*.container' ! -name '*.pod' ! -name '*.volume' ! -name '*.network'`
  returns empty.

## 4. Parity test

- [ ] 4.1 Add `tools/tests/test_render_parity.py`: build a synthetic Module with
  `files/`, `modprobe.d/`, `env/`, `quadlet/` populated; assert both
  `render_bootc` output and `render_ansible` output reference all four
  destinations. (Design D4)

## 5. Verify

- [ ] 5.1 `cd tools && python -m pytest -q` — green, count rises by the new test.
- [ ] 5.2 `aipc render bootc --image-ref test --build-date <today> --out /tmp/cf` —
  exits 0; grep confirms `/etc/containers/systemd/` appears for at least one
  enabled quadlet module (note: all 15 are `.disabled`, so this may only appear
  once a module is enabled — verify instead with a temporary un-disable in a
  scratch checkout, or assert via the parity test's synthetic module).
- [ ] 5.3 `aipc render ansible` + `ansible-lint` — exit 0.
- [ ] 5.4 `openspec validate quadlet-render-support --strict` — passes.
- [ ] 5.5 RED FLAG scan: no `systemctl --now` / `nc -z` / `psql -c` added to any
  post-install.sh (the removals in task 3 should reduce these, not add).

## 6. Docs

- [ ] 6.1 Update `llm-litellm/README.md` and `llm-lemonade/README.md` to reflect
  renderer-owned placement (no hand-install language).
- [ ] 6.2 One-line note in the changed modules' READMEs: "quadlet units placed by
  the renderer into /etc/containers/systemd/".

## Constraints

- Do NOT remove `.disabled` from any module. This is a renderer fix, not enablement.
- Do NOT change any container image reference / digest (Open Q1, out of scope).
- Use `aipc log append` for the agent-log row. Never sed.
