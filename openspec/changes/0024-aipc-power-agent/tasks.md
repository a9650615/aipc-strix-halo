# tasks — 0024-aipc-power-agent

- [x] `backfeed.py` + `core_parking.py` + `agent.py`
- [x] `aipc-power-agent.service` with Alias=power-guard.service
- [x] nested `config.yaml` under `/etc/aipc/power-agent/`
- [x] post-install / verify / README
- [x] CLI `power-agent` + legacy `power-guard` alias
- [x] tests: charge-cap + core_parking + config normalize
- [ ] Live-hotfix on AI PC (optional, operator): stop old units, install, start agent
