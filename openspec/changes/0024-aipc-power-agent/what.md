# what — 0024-aipc-power-agent

## Unit

- **Add** `aipc-power-agent.service` (`ExecStart=/usr/bin/python3 /usr/lib/aipc-power-agent/agent.py`)
- **Alias** `power-guard.service` → same unit (transitional)
- **Stop shipping** a separate `aipc-usbc-core-policy` unit from this module;
  post-install disables any leftover live unit

## Code layout

```
/usr/lib/aipc-power-agent/
  agent.py          # poll loop + config load + state
  backfeed.py       # BackfeedGuard (PowerGuard alias)
  core_parking.py   # CoreParking (former usbc policy)
/etc/aipc/power-agent/config.yaml
/var/lib/aipc-power-agent/state.json
```

## CLI

- `aipc power-agent enable|disable|status`
- `aipc power-guard …` remains as alias

## Kill switches

| File | Effect |
|---|---|
| `/etc/aipc/power-agent.disabled` | whole agent not started / frozen |
| `/etc/aipc/power-agent/backfeed.disabled` | backfeed policy only |
| `/etc/aipc/power-guard.disabled` | legacy backfeed switch still honoured |
| `/etc/aipc/power-agent/core-parking.disabled` | core parking only |
