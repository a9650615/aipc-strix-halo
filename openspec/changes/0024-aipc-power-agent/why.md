# why — 0024-aipc-power-agent

Two host daemons both polled sysfs every 3s and both wrote CPU power knobs:

1. `power-guard` — weak-AC back-feed clamp + charge cap (good hardware guardrail)
2. `aipc-usbc-core-policy` — park half CPUs on power-saver (needed UX; misleading name)

They shared I/O shape but not decision logic. Keeping two units invited
drift (live usbc policy existed only as `/usr/local/sbin` hotfix, not in the
module tree) and confused operators ("who is changing power?").

Integrate into **one agent, two orthogonal policies**, service name
`aipc-power-agent` (aipc- prefix). Do **not** merge triggers into one state
machine (that recreated the USB-C⇒park-cores footgun).
