# agent-tools-files

File-IO path allowlist for agents (D5).

All file read/write operations go through this module. Paths outside
the allowlist require the risky-action gate before access is granted.

Default scopes: ~/projects, ~/Documents

## Dependencies
- system-base

## Spec
openspec/changes/phase-4-agent — task 1.5
