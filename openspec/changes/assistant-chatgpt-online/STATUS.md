# Status — assistant-chatgpt-online (complete v0 + extras)

## Commits
- `d005379` feat aggregator + multi-site engine v0
- `8a24ad4` enable packs, hardware path, timeouts helpers
- `931707f` headless default (no desktop steal)
- (this) docs, packs, render, doctor catalog

## Verified without desktop interrupt
- Module verify.sh green
- openspec validate --strict
- `aipc render bootc` + `aipc render ansible` include both modules
- Headless engine launch (`headless: true`)
- sites plan without browser
- Prior hardware (user session): inject / online turn / voice start-stop / auth export

## Policy
- Automation: **headless only** unless `auth login` / `AIPC_WEB_HEADED=1`
- NPU-first: control + local chat via `resident-small` (`runtime.yaml` auto fallback)
- Multi-site: `sites.yaml` + site packs

## Still optional (not required for v0 done)
- 9.1 dedicated POST :4100/context endpoint
- 9.2 mem0 write-back of ChatGPT transcripts
- 9.3 two-phase confirm keywords
- Full PipeWire system_audio graph (stub returns clear error)
- Long-running online timeout daemon
