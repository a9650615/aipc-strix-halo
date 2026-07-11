# STATUS: cloud-llm-fallback

**State:** provisioning complete in-tree; **routing policy superseded**.

## What remains owned by this change

- SOPS cloud key template / decrypt oneshot pattern
- LiteLLM `*-cloud` alias entries and `EnvironmentFile` wiring
- `models.yaml` cloud alias rows

These are runtime provisioning requirements. Do not delete them when
resolving the active-change conflict with `0002-assistant-intelligence-routing`.

## What is superseded (do not re-implement from this change)

- **Manual-only cloud selection for assistant traffic** — superseded by
  `0002-assistant-intelligence-routing` paid-policy ladder (still off until
  Slice C + hardware gates).
- **No-budget non-goal** for assistant traffic — superseded by 0002 local
  reservation ledger (disabled until configured).

## Conflict resolution (task 0.5 of 0002)

Two active `ai-runtime` deltas must not conflict. This change's
`specs/ai-runtime/spec.md` is **provisioning-only**. Routing authority for
when/whether assistant traffic may use cloud aliases lives entirely in
`0002-assistant-intelligence-routing`.

Archive of this change can proceed later by promoting provisioning requirements
into main `openspec/specs/ai-runtime` without reintroducing manual-only
assistant routing language.
