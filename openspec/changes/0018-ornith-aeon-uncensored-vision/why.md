# Why

The running machine's `ornith-35b` is **not** what the repo says it is. The
repo (`models.yaml`, `litellm/config.yaml`, `llm-lemonade` verify/idle code)
declares `ornith-35b` = `Ornith-1.0-35B-MTP-APEX-I-Balanced` (SC117 APEX,
stock refusal behaviour). But the live `/etc/aipc/litellm/config.yaml` and the
live lemonade registration both point at
`Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-Q4_K_M` (mrexodia GGUF) — an
uncensored fine-tune of the same `deepreinforce-ai/Ornith-1.0-35B` base. This
is a live in-place swap that was never written back to the repo, so a full
image rebuild would silently revert `ornith-35b` to APEX (losing the
uncensored behaviour the user relies on).

Separately, the AEON GGUF ships **text-only** (mrexodia's repo has no mmproj),
so the live `ornith-35b` had lost the vision capability the APEX build had.

The user's decision (2026-07-14): keep the uncensored AEON model **and** give
it vision by borrowing SC117 APEX's `mmproj-F16.gguf` (same base architecture
→ dimensionally compatible). This was already applied and **hardware-verified**
on the live box before this change was written; the change makes that verified
state reproducible across image rebuilds instead of a hand-patch that a rebuild
undoes.
