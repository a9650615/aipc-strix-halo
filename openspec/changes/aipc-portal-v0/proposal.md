# AIPC Portal v0

## Why

Operators currently rely on CLI (`aipc voice status`, `aipc status`, curl)
to check always-on baseline services (resident-small / SenseVoice / Kokoro /
mem0) and peers. A localhost browser entry page is enough to reduce that
friction without building a custom Mem0 UI or remote admin surface.

## What Changes

- New first-class module `system-aipc-portal`: stdlib HTTP entry portal on
  `127.0.0.1:7080`, reading `/etc/aipc/portal/services/*.yaml`.
- Portal metadata YAML cards shipped by baseline modules (mem0, SenseVoice,
  Kokoro, LiteLLM, Lemonade; optional Pipecat helpers card).
- CLI: `aipc portal`, `aipc portal open`, and `aipc portal serve` (live-host
  / pre-bootc fallback).

## Non-goals

- Official Mem0 self-hosted dashboard swap (deferred; not this change).
- Auth, remote bind, reverse proxy, or SPA framework.
- Enabling `.disabled` modules (e.g. CosyVoice).

## Impact

- Adds module: `system-aipc-portal`.
- Adds portal metadata under several existing modules' `files/`.
- Extends `tools/aipc` CLI.
- Local-only listener on `127.0.0.1:7080`.
