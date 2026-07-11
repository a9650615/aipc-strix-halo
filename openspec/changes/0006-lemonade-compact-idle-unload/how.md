# How: Timer-Driven Idle Release, Configured Per Alias

Implement the policy as a small host-side timer job inside `llm-lemonade`.
That keeps the behaviour close to the service that owns the model and avoids
smuggling residency decisions into unrelated memory-pressure code.

The job queries Lemonade health, reads the model manifest, filters loaded and
non-pinned opt-in models, compares Lemonade's monotonic-millisecond
`last_use` value with the host monotonic clock, and unloads one expired model
per pass. It skips models whose status is `in_use`.

The code path does not hardcode `coder-compact`; future aliases opt in by
adding the same metadata field in `models.yaml`.
