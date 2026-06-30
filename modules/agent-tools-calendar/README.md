# agent-tools-calendar

Calendar integration (D8): Google OAuth, Proton (via Bridge), Fastmail CalDAV.

No secrets are baked into the image. The user configures providers
at firstboot via `aipc agent oauth google` or manual CalDAV setup.

## Dependencies
- llm-litellm
- secrets-sops (for credential storage at runtime)

## Spec
openspec/changes/phase-4-agent — task 1.6
