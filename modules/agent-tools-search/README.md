# agent-tools-search

Search backend: SearXNG (default, local container) + Tavily (opt-in, API key).

SearXNG runs as a quadlet container bound to loopback.
Tavily is only advertised when `TAVILY_API_KEY` is set in the
SOPS-encrypted secrets.

## Dependencies
- secrets-sops (Tavily API key decryption)
- llm-litellm

## Spec
openspec/changes/phase-4-agent — task 1.7
