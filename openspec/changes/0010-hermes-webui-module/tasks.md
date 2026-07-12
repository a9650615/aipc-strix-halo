# Tasks — hermes-webui-module

- [ ] 1. Create `modules/dev-ai-hermes-webui/` with README, packages.txt.
- [ ] 2. Ship the user unit + `default.target.wants` auto-enable symlink.
- [ ] 3. Ship `setup-hermes-webui.sh` + `aipc-hermes-webui-setup.service` oneshot.
- [ ] 4. Move the portal `hermes-webui.yaml` card from agent-orchestrator to this module.
- [ ] 5. post-install.sh (enable oneshot, chmod; build-time only) + verify.sh.
- [ ] 6. Render-verify: bootc + ansible both include the module, symmetric (§4).
- [ ] 7. Hardware-verify on a fresh image boot: setup oneshot clones/updates the
      checkout, enables linger, and the user unit auto-starts on `:8788`.
      (Deferred — needs a bootc rebuild+reboot; runtime pattern already proven in 0009.)
