# dev-cli

Fish shell, Starship prompt, and a curated CLI bundle for daily development.

## Packages from bazzite-dx / Fedora repos

fish, gh, zoxide, bat, eza, jetbrains-mono-fonts, fira-code-fonts.

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

## Dependencies

- `system-base`.

## Consumers

Every interactive shell session. AI CLI tools inherit the fish + starship env.
