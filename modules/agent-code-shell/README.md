# agent-code-shell

Distrobox sandbox for agent code execution (D3).

The agent-runtime distrobox provides an isolated Fedora environment
where code execution tools (open-interpreter, etc.) run safely.
The distrobox-assemble template is installed at build time; the box
is spawned on first boot by the user.

## Dependencies
- dev-distrobox-templates
- llm-litellm

## Spec
openspec/changes/phase-4-agent — task 1.2
