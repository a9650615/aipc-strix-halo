# dev-editors

Zed (primary, D1) and VSCode (secondary) editors.

## Design decision D1

Zed is the primary editor for daily coding. VSCode is kept as secondary to
host the Continue.dev and Cline extensions (`dev-ai-continue`, `dev-ai-cline`).

## Packages from Fedora repos

code (VSCode), google-jetbrains-mono-fonts, fira-code-fonts.

## Zed

Installed via flatpak (`dev.zed.Zed`) in post-install.sh. Skel config at
`/etc/skel/.config/zed/settings.json` points Zed's AI assistant at LiteLLM.

## Dependencies

- `system-base` (flatpak runtime).

## Consumers

- `dev-ai-continue` and `dev-ai-cline` install VSCode extensions.
