# Tasks

- [x] 1.1 Add a failing test for oversized tool-result artifact preservation and bounded prompt insertion.
- [x] 1.2 Implement bounding in Hermes' shared tool-result insertion path.
- [x] 2.1 Add failing tests for rollover, one-time notice, pending-message carryover, and side-effect non-replay.
- [x] 2.2 Implement successor-session creation with compact and deterministic handoff paths.
- [x] 3.1 Ship reproducible Hermes settings for a 131,072-token window, 0.70 compression threshold, and four protected tail messages.
- [x] 3.2 Add a synthetic 128K-class regression that forces an unrecoverable protected tail.
- [x] 4.1 Run Hermes focused tests, static checks, and strict OpenSpec validation.
- [x] 4.2 Render bootc and ansible and run render parity.
- [ ] 4.3 Apply the repository-first live hotfix and hardware-verify rollover on the Strix Halo host. (Hermes `main` and live YAML are updated; a real 128K model soak remains pending.)
- [x] 4.4 Record verification tiers and append the agent log.
