# How: Repoint + Relocate, Via the Live-Hotfix Loop

1. Edit the repo unit `modules/llm-lemonade/files/etc/systemd/system/lemonade.service`
   (the durable source of truth) — change the HF cache `mkdir` and the bind
   volume to `/var/lib/aipc-models/hf`.
2. Live-deploy per `docs/live-hotfix-workflow.md`: `sudo cp` the unit to
   `/etc/systemd/system/lemonade.service`, `daemon-reload`, `systemctl restart`.
3. One downtime window: stop Lemonade, move the live model dirs
   (`Ornith-1.0-35B-GGUF`, `gemma-4-26B-A4B-it-GGUF`) from the old hub into
   `/var/lib/aipc-models/hf/hub` (same btrfs filesystem → instant rename, no
   extra space), restart. Podman's `:Z` relabel handles SELinux on the new
   path automatically.
4. Stale duplicates in the old cache (e.g. the ~54G `Qwen3.5-122B-A10B-GGUF`
  left behind when that model moved to Ollama) are deleted, not relocated.

## Verification (hardware-verified 2026-07-09)

- `lemonade.service` active; `ExecStartPre` mkdir of `/var/lib/aipc-models/hf`
  exits 0.
- lemond boots: `NPU hardware: Yes`, `ModelManager Cache built: 144 total,
  4 downloaded` — confirms it reads the relocated weights.
- Zero SELinux `container_file_t` denials after the `:Z` relabel.
- `/api/v0/models` responds.
- Rollback: `/etc/systemd/system/lemonade.service.bak-pre-hf-repoint`.

## Not in scope

- Migrating Lemonade's `cache`/`flm` mounts (not weights).
- Consolidating `~/.cache/huggingface` (user-space, unrelated).
- A CLI to dedupe across backends — the shared root makes duplication
  *visible*; automated dedup is future work.
