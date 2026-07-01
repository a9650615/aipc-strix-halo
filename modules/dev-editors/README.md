# dev-editors

Zed (primary, D1) and VSCode (secondary) editors.

## Design decision D1

Zed is the primary editor for daily coding. VSCode is kept as secondary to
host the Continue.dev and Cline extensions (`dev-ai-continue`, `dev-ai-cline`).

## Build-time vs runtime split

`packages.txt` installs **build-time only** dev fonts (`jetbrains-mono`,
`fira-code-fonts`) via rpm. Editors themselves (VSCode, Zed, JetBrains
Client) are **not** installed at build time:

- VSCode is not a Fedora rpm — bazzite ships IDEs via Brew/Flatpak/ujust.
- `flatpak install` requires network access, which violates the offline-build
  contract (post-install.sh runs at image-build time, no network allowed).

Users install editors at runtime via:
- `flatpak install flathub dev.zed.Zed` (Zed)
- `flatpak install flathub com.visualstudio.code` (VSCode)
- `ujust ide install jetbrains-client` (JetBrains CL)

Skel configs at `/etc/skel/.config/zed/settings.json` and
`/etc/skel/.config/Code/settings.json` route AI assistant calls to the
LiteLLM gateway once the user installs the corresponding editor.

## Packages from Fedora repos

jetbrains-mono-fonts, fira-code-fonts.

## Zed and VSCode

Runtime-installed by user via flatpak. Skel configs point AI assistants at
LiteLLM (`http://127.0.0.1:4000`).

## Dependencies

- `system-base` (flatpak runtime).

## Consumers

- `dev-ai-continue` and `dev-ai-cline` install VSCode extensions.
