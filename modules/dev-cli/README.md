# dev-cli

Fish shell, Starship prompt, and a curated CLI bundle for daily development.

## Packages from bazzite-dx / Fedora repos

fish, gh, zoxide, bat, eza, jetbrains-mono-fonts, fira-code-fonts, btop.

Deduped against `system-base` (which already provides git-delta, fzf, ripgrep,
jq, yq, httpie).

## Packages requiring manual install (not in Fedora repos)

Not shipped in the image; user installs on first login. All install to `~/.local`
or `~/.cargo` — no root required after these tools bootstrap.

- **starship**: prompt — `curl -sS https://starship.rs/install.sh | sh -s -- -y`.
- **lazygit**: git TUI — `go install github.com/jesseduffield/lazygit@latest` or brew tap.
- **ghostty**: terminal emulator — install from <https://ghostty.org>.
- **mise**: polyglot tool version manager — `curl https://mise.run | sh`.
- **atuin**: shell history sync — `curl --proto '=https' --tlsv1.2 -LsSf https://setup.atuin.sh | sh`.

## post-install.sh

- Sets fish as the primary user's login shell (`chsh`).
- Grants `btop` `cap_dac_read_search` so its CPU-watts reading (RAPL package power via
  `/sys/class/powercap/intel-rapl:0/energy_uj`, root-only 0400 by default) works for the
  regular user without sudo. Hardware-verified 2026-07-04: on this APU, that RAPL package
  reading, `rocm-smi`'s "Socket Graphics Package Power", and `amdgpu`'s hwmon
  `power1_input` are all the same combined SoC power rail (measured within ~0.03W of each
  other) — there is no separate CPU-only vs GPU-only power sensor on this hardware, so
  btop's CPU box and GPU box watts will read the same number. `~/.config/btop/btop.conf`
  needs `show_cpu_watts = true` (default) and `shown_boxes` to include `gpu0`; this is a
  per-user dotfile, not shipped by this module.

## Dependencies

- `system-base`.

## Consumers

Every interactive shell session. AI CLI tools inherit the fish + starship env.
