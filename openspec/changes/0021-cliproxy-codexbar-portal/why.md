# Why — cliproxy-codexbar-portal

Hermes multi-model collab depends on two subscription-side bridges that already
run as **user** systemd units:

1. **CLIProxy** (`ccs-cliproxy`, `:8317`) — OpenAI-compatible OAuth bridge for
   Codex/Claude/Gemini (and Hermes `custom:cliproxy`).
2. **CodexBar usage** (`aipc-usage`, `:8080`) — quota HTTP API used by
   `check_subscription_quota` / peer-agent gates.

Control Center already manages system units (LiteLLM, Lemonade, mem0…). These
two bridges are invisible there: portal only probes `systemctl` on the system
bus, so operators cannot see or Start them from the dashboard even though they
are first-class collab dependencies.

Same design pressure as hermes-webui: OAuth tokens live under `$HOME`, so the
units stay **user-scope** (system unit + home paths = SELinux / permission
pain). Portal must grow `systemd_scope: user` instead of forcing system units.
