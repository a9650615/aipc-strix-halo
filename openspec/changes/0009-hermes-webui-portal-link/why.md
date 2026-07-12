# Why — hermes-webui-portal-link

Hermes (NousResearch `hermes-agent`) is the heavyweight agent the voice
orchestrator delegates tool-heavy turns to. It has no first-party HTTP surface,
so today the only way to inspect or drive it directly is the CLI. The mature
`nesquena/hermes-webui` project is a turnkey web console for exactly this
agent: it auto-discovers our existing `~/.hermes/hermes-agent` checkout, reuses
the same `~/.hermes/config.yaml` (so model calls still route through LiteLLM per
CLAUDE.md §7), and its CLI-session bridge surfaces the very `source_tag:
aipc-voice` sessions our orchestrator creates.

We are running hermes-webui as a loopback service on `127.0.0.1:8788` (default
8787 is taken by codexbar-gui). The Control Center dashboard should expose a
link to it, but the portal SPA currently renders only `title: state` + a Start
button per service — it never surfaces the `ui:` field that service cards
already declare. This change makes the dashboard show an "Open UI" link so
hermes-webui (and any future UI-bearing service) is reachable from the portal.
