# dev-cli

Fish shell, Starship prompt, and a curated CLI bundle for daily development.

## Packages from Fedora repos

fish, starship, gh, git-delta, fzf, ripgrep, jq, yq, httpie, zoxide, bat, eza,
lazygit, jetbrains-mono-fonts, fira-code-fonts.

## Packages requiring manual install (not in Fedora repos)

- **ghostty**: terminal emulator — install from <https://ghostty.org>.
- **mise**: polyglot tool version manager — `curl https://mise.run | sh`.
- **atuin**: shell history sync — `cargo install atuin` or official script.

## post-install.sh

- Sets fish as the primary user's login shell (`chsh`).

## Dependencies

- `system-base`.

## Consumers

Every interactive shell session. AI CLI tools inherit the fish + starship env.
